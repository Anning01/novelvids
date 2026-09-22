"""Bounded wire projections; compact model context without deleting the audit trail."""

from dataclasses import replace
import json
import math

from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart, UserPromptPart

from models.creation_agent import AgentContextCheckpoint


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True, default=str)


def wire_size(messages, parameters) -> dict:
    # Instructions are hoisted once by the installed OpenAI adapter. SDK run IDs,
    # timestamps and usage are not part of the model's conversation payload.
    instructions = next((m.instructions for m in reversed(messages)
                         if isinstance(m, ModelRequest) and m.instructions), '')
    tools = [dict(name=t.name, description=t.description, parameters=t.parameters_json_schema)
             for t in [*parameters.function_tools, *parameters.output_tools]]
    segments = {'instructions': len(instructions or ''), 'tools': len(encode(tools)),
                'history': 0, 'objects': 0}
    for message in messages:
        for part in message.parts:
            if isinstance(part, ToolReturnPart):
                segments['objects'] += len(encode(part.content)) + len(part.tool_name) + 24
            elif isinstance(part, ToolCallPart):
                segments['history'] += len(part.args_as_json_str()) + len(part.tool_name) + 24
            else:
                segments['history'] += len(str(getattr(part, 'content', ''))) + 16
    return {**segments, 'total_characters': sum(segments.values())}


class ContextBudget:
    """Per-run working-set controller, with durable recovery references."""

    def __init__(self, limits, message=None, on_compact=None):
        self.limits = limits
        self.message = message
        self.on_compact = on_compact
        self.characters_per_token = 2.0
        self.compactions = 0
        self.last_report = {}
        self.replacements = {}
        self.archives = {}
        self.keep_from_run_id = None
        self.keep_from_user_content = None

    def observe(self, report, usage):
        if usage and usage.input_tokens:
            ratio = report['total_characters'] / usage.input_tokens
            # Conservative calibration; never assume that CJK tokenizes like English.
            self.characters_per_token = min(self.characters_per_token, max(0.5, ratio * 0.9))

    def report(self, messages, parameters):
        report = wire_size(messages, parameters)
        report['estimated_input_tokens'] = math.ceil(report['total_characters'] / self.characters_per_token)
        return report

    async def prepare(self, messages, parameters, *, force=False):
        from services.creation_agent.history import compact_retry_history
        messages = self.restore_projection(compact_retry_history(messages))
        report = self.report(messages, parameters)
        ceiling = min(self.limits.max_context_characters,
                      int(self.limits.working_input_tokens * self.characters_per_token))
        if not force and report['total_characters'] <= ceiling * self.limits.compaction_trigger_ratio:
            self.last_report = report
            return messages
        if self.on_compact:
            await self.on_compact()
        target = max(report['instructions'] + report['tools'] + 2000, ceiling * self.limits.compaction_target_ratio)
        returns = [(i, j, p) for i, m in enumerate(messages) for j, p in enumerate(m.parts)
                   if isinstance(p, ToolReturnPart) and not (isinstance(p.content, dict) and 'archive_ref' in p.content)]
        completed = {p.tool_call_id for _, _, p in returns}
        result = [replace(m, parts=list(m.parts)) for m in messages]
        # Only completed calls may be compacted. Pending tool inputs stay intact.
        for i, message in enumerate(result):
            for j, part in enumerate(message.parts):
                if isinstance(part, ToolCallPart) and part.tool_call_id in completed and len(part.args_as_json_str()) > 800:
                    result[i].parts[j] = replace(part, args={'completed': True, 'tool_call_id': part.tool_call_id})
                    self.replacements[('call', part.tool_call_id)] = result[i].parts[j]
        for i, j, part in returns:
            if self.report(result, parameters)['total_characters'] <= target:
                break
            # Keep the newest read usable if it fits the hard ceiling. Offloading
            # that result immediately would create an endless re-read loop.
            if not force and returns and part is returns[-1][2] and self.report(result, parameters)['total_characters'] <= self.limits.max_context_characters:
                continue
            if len(encode(part.content)) < 800:
                continue
            # Latest results may also be offloaded, but can be paged back through
            # read_creation_history. Never pretend a preview is a full object.
            reference = await self._archive(part)
            result[i].parts[j] = replace(part, content=reference)
            self.replacements[('return', part.tool_call_id)] = result[i].parts[j]
        # Drop only complete earlier turns, never the current user's instruction.
        starts = [i for i, m in enumerate(result) if isinstance(m, ModelRequest)
                  and any(isinstance(p, UserPromptPart) for p in m.parts)]
        while len(starts) > 1 and self.report(result, parameters)['total_characters'] > target:
            boundary = starts[1]
            old = result[:boundary]
            excerpt = '\n'.join(str(p.content)[:300] for m in old for p in m.parts
                                if isinstance(p, UserPromptPart))
            if self.message and getattr(self.message, 'conversation_id', None):
                from pydantic_ai.messages import ModelMessagesTypeAdapter
                await AgentContextCheckpoint.create(conversation_id=self.message.conversation_id,
                    message_id=self.message.id, kind='turn_archive', content=excerpt,
                    payload=json.loads(ModelMessagesTypeAdapter.dump_json(old)))
            boundary_message = result[boundary]
            self.keep_from_run_id = boundary_message.run_id
            self.keep_from_user_content = next(
                (part.content for part in boundary_message.parts if isinstance(part, UserPromptPart)),
                None,
            )
            result = result[boundary:]
            starts = [i - boundary for i in starts[1:]]
        self.compactions += 1
        self.last_report = self.report(result, parameters)
        self.last_report['compactions'] = self.compactions
        if self.last_report['total_characters'] > self.limits.max_context_characters:
            raise ValueError('上下文超过配置上限：当前要求或必要约束无法在预算内完整处理')
        return result

    def restore_projection(self, messages):
        result = []
        for message in messages:
            parts = []
            for part in message.parts:
                kind = 'call' if isinstance(part, ToolCallPart) else 'return' if isinstance(part, ToolReturnPart) else None
                parts.append(self.replacements.get((kind, getattr(part, 'tool_call_id', None)), part))
            result.append(replace(message, parts=parts))
        if self.keep_from_run_id or self.keep_from_user_content is not None:
            for index, message in enumerate(result):
                same_run = self.keep_from_run_id and message.run_id == self.keep_from_run_id
                same_prompt = self.keep_from_user_content is not None and any(
                    isinstance(part, UserPromptPart) and part.content == self.keep_from_user_content
                    for part in message.parts
                )
                if same_run or same_prompt:
                    return result[index:]
        return result

    async def _archive(self, part):
        payload = part.content
        if part.tool_call_id in self.archives:
            return self.archives[part.tool_call_id]
        if self.message and getattr(self.message, 'conversation_id', None):
            checkpoint = await AgentContextCheckpoint.create(conversation_id=self.message.conversation_id,
                message_id=self.message.id, kind='tool_archive', content=part.tool_name,
                payload={'tool_call_id': part.tool_call_id, 'content': payload})
            ref = checkpoint.id
        else:
            # Test/standalone runners can always re-read business data.
            ref = None
        constraints = []
        def collect(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in ('constraints', 'constraints_for_new_objects') and isinstance(child, list):
                        constraints.extend(child)
                    elif isinstance(child, (dict, list)):
                        collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)
        collect(payload)
        reference = {'constraints': constraints, 'archive_ref': ref, 'tool': part.tool_name, 'tool_call_id': part.tool_call_id,
                'preview': encode(payload)[:320], 'content_truncated': True,
                'recovery': 'read_creation_history(archive_id=archive_ref)，或重新按字段读取对象',
                **({'status': payload['status'], 'change_id': payload.get('change_id')}
                   if isinstance(payload, dict) and 'status' in payload else {})}

        self.archives[part.tool_call_id] = reference
        return reference
