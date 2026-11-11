"""Run the production conversation with Deep Agents and the existing task/event services."""

import posixpath
from pathlib import Path
from scripts.export_skill import LINK
from functools import partial

from deepagents.backends.utils import create_file_data
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from config import settings
from utils.enums import TaskStatusEnum
from models.creation_agent import AgentMessage
from prompts.deep_agent import PROFESSIONAL_SKILLS, instructions, user_request, summary_instructions
from prompts.skill_pack import FILES
from services.creation_agent.deep_model import RecordedChatModel, working_context_tokens
from services.creation_agent.deep_runtime import create_runtime, public_events
from services.creation_agent.deep_tools import business_tools
from services.creation_agent.project_facts import CATALOG_PATH, load_project_facts


def skill_files(snapshot):
    resources = {path: snapshot.contents[key] for key, path in FILES.items() if key in snapshot.contents}
    files = {}
    for stage in PROFESSIONAL_SKILLS:
        package = f'novelvids-{stage}'
        entry = f'{package}/SKILL.md'
        if entry not in resources:
            continue
        def include(match):
            source = posixpath.normpath(posixpath.join(package, match[2]))
            relative = '/'.join(source.split('/')[-2:])
            if source not in resources:
                raise ValueError(f'Missing skill reference: {source}')
            if source in resources:
                files[f'/skills/{package}/{relative}'] = create_file_data(resources[source])
            return f'{match[1]}{relative}{match[3]}'
        files['/skills/' + entry] = create_file_data(LINK.sub(include, resources[entry]))
    return files


async def stream_deep_agent(*, request, conversation, assistant, deps, recorded, execution, before_request, model_settings):
    await before_request()
    facts, manifest = await load_project_facts(novel_id=conversation.novel_id, chapter_id=request.chapter_id,
        page_size=deps.limits.max_targets, character_budget=deps.limits.context_page_characters, authorize=before_request)
    tools = await business_tools(deps, recorded, before_request)
    model = RecordedChatModel(recorded=recorded,
        profile={'max_input_tokens': deps.limits.working_input_tokens, 'tool_calling': True},
        settings=model_settings)
    path = Path(settings.CREATION_AGENT_CHECKPOINT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    scope = {'write_scope': request.write_scope, 'chapter_id': request.chapter_id,
             'selected_targets': [target.model_dump() for target in request.targets]}
    turn_ids = await AgentMessage.filter(conversation_id=conversation.id, role='user', id__lt=assistant.id).exclude(task_id=assistant.task_id).order_by('-id').limit(deps.limits.history_runs).values_list('task_id', flat=True)
    recent = await AgentMessage.filter(conversation_id=conversation.id, role='assistant', task_id__in=turn_ids).order_by('-id').select_related('task')
    lifecycle = [{'run_id': str(item.task_id), 'status': TaskStatusEnum(item.task.status).name}
                 for item in recent if not (item.run_input or {}).get('internal_production_step')]
    optimizer = execution.params.get('video_optimizer', {})
    context = {**deps.context, 'video_optimizer': {key: value for key, value in optimizer.items() if key != 'files'}, 'project_facts': facts,
        'current_turn': {'run_id': str(assistant.task_id), 'user_request': request.message, 'authorized_scope': scope},
        'recent_run_states': lifecycle}
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        graph = create_runtime(model=model, tools=tools, instructions=instructions(execution.language, context),
            checkpointer=saver, summarization={
                'summary_prompt': summary_instructions(execution.language),
                'token_counter': partial(working_context_tokens, token_budget=deps.limits.working_input_tokens, character_limit=recorded.max_characters),
                'trim_tokens_to_summarize': int(deps.limits.working_input_tokens * deps.limits.compaction_trigger_ratio),
                'trigger': ('tokens', int(deps.limits.working_input_tokens * deps.limits.compaction_trigger_ratio)),
                'keep': ('tokens', int(deps.limits.working_input_tokens * deps.limits.compaction_target_ratio)),
            })
        thread_id = f'conversation:{conversation.id}'
        state = await graph.aget_state({'configurable': {'thread_id': thread_id}})
        history = []
        if not state.values:
            previous = await AgentMessage.filter(conversation_id=conversation.id, id__lt=assistant.id).exclude(task_id=assistant.task_id).order_by('id')
            history = [(HumanMessage if item.role == 'user' else AIMessage)(content=item.content)
                       for item in previous if item.content and not (item.run_input or {}).get('internal_production_step')]
        inputs = {'messages': [*history, HumanMessage(content=user_request(request.message, scope))],
                  'files': {**skill_files(execution.snapshot),
                    **{f'/skills/{optimizer["skill"]}/{name}': create_file_data(content) for name, content in optimizer.get('files', {}).items()}, CATALOG_PATH: create_file_data(manifest)}}
        try:
            async for event in public_events(graph, inputs, thread_id=thread_id, run_id=str(assistant.task_id)):
                if 'threadId' in event:
                    event['threadId'] = str(conversation.id)
                yield event
        except Exception as error:
            # The task handler applies the same public-error redaction as the legacy adapter.
            yield {'type': 'RUN_ERROR', 'message': str(error)}
