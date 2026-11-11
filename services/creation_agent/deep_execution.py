"""Run the production conversation with Deep Agents and the existing task/event services."""

from pathlib import Path
from functools import partial

from deepagents.backends.utils import create_file_data
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from config import settings
from models.creation_agent import AgentMessage
from prompts.deep_agent import PROFESSIONAL_SKILLS, instructions, user_request
from prompts.skill_pack import FILES
from services.creation_agent.deep_model import RecordedChatModel, working_context_tokens
from services.creation_agent.deep_runtime import create_runtime, public_events
from services.creation_agent.deep_tools import business_tools


def skill_files(snapshot):
    packages = {f'novelvids-{name}' for name in PROFESSIONAL_SKILLS}
    return {'/skills/' + path: create_file_data(snapshot.contents[name])
            for name, path in FILES.items() if path.split('/')[0] in packages and name in snapshot.contents}


async def stream_deep_agent(*, request, conversation, assistant, deps, recorded, execution, before_request, model_settings):
    await before_request()
    tools = await business_tools(deps, recorded, before_request)
    model = RecordedChatModel(recorded=recorded,
        profile={'max_input_tokens': deps.limits.working_input_tokens, 'tool_calling': True},
        settings=model_settings)
    path = Path(settings.CREATION_AGENT_CHECKPOINT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    scope = {'write_scope': request.write_scope, 'chapter_id': request.chapter_id,
             'selected_targets': [target.model_dump() for target in request.targets]}
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        graph = create_runtime(model=model, tools=tools, instructions=instructions(execution.language, deps.context),
            checkpointer=saver, summarization={
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
                  'files': skill_files(execution.snapshot)}
        try:
            async for event in public_events(graph, inputs, thread_id=thread_id, run_id=str(assistant.task_id)):
                if 'threadId' in event:
                    event['threadId'] = str(conversation.id)
                yield event
        except Exception as error:
            # The task handler applies the same public-error redaction as the legacy adapter.
            yield {'type': 'RUN_ERROR', 'message': str(error)}
