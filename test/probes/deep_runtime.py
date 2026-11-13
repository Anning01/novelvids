"""Run with the isolated Deep Agents Python environment; no project dependency changes."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from deepagents.backends.utils import create_file_data
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import Field

from services.creation_agent.deep_runtime import create_runtime, public_events

SKILLS = ('story', 'screenplay', 'assets', 'image', 'storyboard', 'video', 'remake')


class ScriptedModel(BaseChatModel):
    model_name: str = 'python-probe'
    profile: dict = Field(default_factory=lambda: {'max_input_tokens': 8192, 'tool_calling': True})

    @property
    def _llm_type(self):
        return 'python-probe'

    def bind_tools(self, tools, **kwargs):
        return self.bind(tools=tools, **kwargs)

    def response(self, messages, tools):
        if not tools:
            return AIMessage(content='INTERNAL_SUMMARY_SENTINEL：只写第二章，第一章保持原样。恢复后先读取当前版本。')
        names = {item.name if hasattr(item, 'name') else item['name'] for item in tools}
        assert names == {'read_file', 'read_chapter', 'save_chapter'}, names
        last_user = max(index for index, message in enumerate(messages) if isinstance(message, HumanMessage))
        results = [message for message in messages[last_user + 1:] if isinstance(message, ToolMessage)]
        instruction = messages[last_user].content
        def call(name, args, identifier):
            return {'name': name, 'args': args, 'id': identifier, 'type': 'tool_call'}
        if '越权' in instruction:
            return AIMessage(content='越权调用必须被拒绝。', tool_calls=[call('write_file', {'file_path': '/escape.txt', 'content': 'forbidden'}, 'escape')]) if not results else AIMessage(content='越权工具已被服务端拒绝。')
        if '长会话' in instruction:
            return AIMessage(content='已记录只改第二章。')
        if not results:
            return AIMessage(content='我会核对两章，只调整第二章。', tool_calls=[
                call('read_file', {'file_path': '/skills/story/SKILL.md'}, 'skill'),
                call('read_chapter', {'chapter_id': 1}, 'read-1'),
                call('read_chapter', {'chapter_id': 2}, 'read-2')])
        if len(results) == 3:
            return AIMessage(content='', tool_calls=[call('save_chapter', {
                'chapter_id': 2, 'text': '第二章：林舟想起阿宁，低声回应灯塔的信号。'}, 'write')])
        return AIMessage(content='第二章已调整，第一章保持原文。')

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self.response(messages, kwargs.get('tools')))])

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        result = self.response(messages, kwargs.get('tools'))
        for text in (result.content[index:index + 5] for index in range(0, len(result.content), 5)):
            yield ChatGenerationChunk(message=AIMessageChunk(content=text))
            await asyncio.sleep(0)
        if result.tool_calls:
            yield ChatGenerationChunk(message=AIMessageChunk(content='', tool_calls=result.tool_calls))
        else:
            yield ChatGenerationChunk(message=AIMessageChunk(content='',
                usage_metadata={'input_tokens': 200, 'output_tokens': 20, 'total_tokens': 220}))


class PythonRuntimeProbe(unittest.IsolatedAsyncioTestCase):
    async def test_sdk_skills_stream_and_checkpoint_resume(self):
        with TemporaryDirectory() as directory:
            chapters = {1: '第一章：林舟在渡口遇见阿宁。', 2: '第二章：林舟在灯塔听见信号。'}
            reads, writes = [], []

            @tool
            async def read_chapter(chapter_id: int) -> str:
                """Read current chapter content."""
                reads.append(chapter_id)
                return chapters[chapter_id]

            @tool
            async def save_chapter(chapter_id: int, text: str) -> str:
                """Save only the selected target chapter."""
                if chapter_id != 2:
                    raise ValueError('Only chapter 2 is writable')
                writes.append(chapter_id)
                chapters[chapter_id] = text
                return 'saved'

            tools = [read_chapter, save_chapter]
            files = {f'/skills/{name}/SKILL.md': create_file_data(
                f'---\nname: {name}\ndescription: {name} 专业技能\n---\n只处理本专业内容。') for name in SKILLS}
            database = str(Path(directory) / 'checkpoints.db')
            async with AsyncSqliteSaver.from_conn_string(database) as saver:
                graph = create_runtime(model=ScriptedModel(), tools=tools, instructions='只读跨章证据，只写目标第二章。', checkpointer=saver, summarization={'trigger': ('messages', 12), 'keep': ('messages', 4)})
                events = [event async for event in public_events(graph,
                    {'messages': [HumanMessage('跨章取证并定向改稿')], 'files': files}, thread_id='probe', run_id='first')]
                self.assertEqual(reads, [1, 2])
                self.assertEqual(writes, [2])
                self.assertEqual(chapters[1], '第一章：林舟在渡口遇见阿宁。')
                self.assertTrue(any(event['type'] == 'TOOL_CALL_RESULT' for event in events))
                self.assertGreater(sum(event['type'] == 'TEXT_MESSAGE_CONTENT' for event in events), 2)
                self.assertEqual(events[-1]['type'], 'RUN_FINISHED')
                state = await graph.aget_state({'configurable': {'thread_id': 'probe'}})
                self.assertEqual(len(state.values['skills_metadata']), 7)
                for index in range(16):
                    emitted = [event async for event in public_events(graph,
                        {'messages': [HumanMessage('长会话测试，只写第二章。' + '用于验证历史上下文压缩的小说资料。' * 50)]},
                        thread_id='probe', run_id=f'long-{index}')]
                    self.assertNotIn('INTERNAL_SUMMARY_SENTINEL', str(emitted))
                state = await graph.aget_state({'configurable': {'thread_id': 'probe'}})
                self.assertTrue('INTERNAL_SUMMARY_SENTINEL' in str(state.values), 'SDK summary must be checkpointed')
                self.assertTrue(any(path.startswith('/conversation_history/') for path in state.values['files']))
                await graph.ainvoke({'messages': [HumanMessage('越权工具调用测试')]}, {'configurable': {'thread_id': 'boundary'}})
                rejected = await graph.aget_state({'configurable': {'thread_id': 'boundary'}})
                self.assertNotIn('/escape.txt', rejected.values.get('files', {}))
                self.assertTrue(any(getattr(message, 'status', None) == 'error' for message in rejected.values['messages']))
            async with AsyncSqliteSaver.from_conn_string(database) as saver:
                resumed = create_runtime(model=ScriptedModel(), tools=tools, instructions='只写第二章。', checkpointer=saver, summarization={'trigger': ('messages', 12), 'keep': ('messages', 4)})
                state = await resumed.aget_state({'configurable': {'thread_id': 'probe'}})
                self.assertTrue(any(isinstance(message, ToolMessage) for message in state.values['messages']))
                await resumed.ainvoke({'messages': [HumanMessage('继续定向改稿')]}, {'configurable': {'thread_id': 'probe'}})
                self.assertEqual(writes, [2, 2])


if __name__ == '__main__':
    unittest.main()
