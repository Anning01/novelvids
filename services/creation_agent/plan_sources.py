"""Read complete bounded source pages and retain verifiable original excerpts."""

import hashlib
import json

from models.chapter import Chapter
from schemas.creation_agent import AgentConfiguration
from schemas.creation_plan import ChapterEvidence, SourceExcerpt, SourceReading
from services.creation_agent.source_references import resolve_reading, resolve_plan_references, source_paragraphs
from prompts.creation_plan import reading_reference_instructions
from utils.messages import localized_message


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def chapter_version(chapter):
    return fingerprint([chapter.id, chapter.number, chapter.name, chapter.production_text])


async def plan_activity(execution, key, label, *, status='completed', detail=''):
    from datetime import datetime, timezone
    from services.creation_agent.event_log import agent_event_log
    from services.task_signals import task_signals

    now = datetime.now(timezone.utc)
    event = {'type': 'CUSTOM', 'name': 'agent_activity', 'timestamp': int(now.timestamp() * 1000),
             'value': {'id': f'creation:{key}', 'kind': 'status', 'label': label, 'detail': detail,
                       'status': status, 'started_at': now.isoformat(),
                       'finished_at': now.isoformat() if status != 'running' else None}}
    # Planning tools run during the chat stream; publish to a private child log
    # to avoid racing the stream's buffered sequence counter.
    from uuid import UUID, uuid5
    from models.creation_agent import AgentMessage
    from models.ai_task import AiTask
    if execution.params.get('operation') == 'creation_plan':
        message = execution.message
    else:
        task_id = uuid5(UUID(str(execution.params['task_id'])), 'creation:activity')
        task, _ = await AiTask.get_or_create(id=task_id, defaults={'task_type': 7, 'status': 3,
            'request_params': {**execution.params, 'parent_task_id': execution.params['task_id']}})
        message, _ = await AgentMessage.get_or_create(task=task, role='assistant', defaults={
            'conversation_id': execution.message.conversation_id, 'request_id': task_id, 'request_hash': str(task_id),
            'run_input': {'internal_production_step': True}})
    seq = await agent_event_log.start(message)
    await agent_event_log.append(message.id, [event], seq)
    await task_signals.publish(str(execution.message.task_id))


class CreationSourceLoader:
    def __init__(self, execution):
        self.execution = execution
        self.novel_id = execution.params['novel_id']

    async def read(self, chapter_ids, requirements):
        limits = AgentConfiguration.model_validate(self.execution.params['agent_configuration'])
        chapters = []
        ids = list(dict.fromkeys(chapter_ids))
        for index, chapter_id in enumerate(ids):
            await self.execution.before_request()
            chapter = await Chapter.get_or_none(id=chapter_id, novel_id=self.novel_id)
            if chapter is None or not (chapter.production_text or '').strip():
                raise ValueError(localized_message('需要阅读的章节不存在或正文为空'))
            version = chapter_version(chapter)
            pages = []
            coverage = []
            for offset in range(0, len(chapter.production_text), limits.context_page_characters):
                end = min(len(chapter.production_text), offset + limits.context_page_characters)
                facts = {
                    'segment': f'{chapter.id}:{version}:{offset}', 'chapter_id': chapter.id,
                    'chapter_number': chapter.number, 'start': offset, 'end': end,
                    'content': chapter.production_text[offset:end], 'requirements': requirements,
                    'paragraphs': source_paragraphs(chapter.production_text[offset:end], offset), 'reference_protocol': 2,
                }
                options = {'additional_instructions': reading_reference_instructions(self.execution.language)}
                page = await self.execution.generate('source_reading', facts, SourceReading, **options)
                # Completed historical receipts are immutable and free to replay.
                # Resolve their old quotations locally before requesting any repair.
                try:
                    page = resolve_reading(page, facts)
                except ValueError as error:
                    await self.execution.claim_repair('source_reading', 'source_reference')
                    repaired = await self.execution.generate('source_reading', {
                        **facts, 'segment': facts['segment'] + ':references:repair:1',
                        'reference_error': str(error),
                    }, SourceReading, **options)
                    page = resolve_reading(repaired, facts, require_paragraphs=True)
                pages.append(page)
                coverage.append((offset, end))
            await chapter.refresh_from_db()
            if chapter_version(chapter) != version:
                raise ValueError(localized_message('阅读期间原文已变化，请重新规划'))
            chapters.append(ChapterEvidence(chapter_id=chapter.id, number=chapter.number, name=chapter.name,
                version=version, characters=len(chapter.production_text), pages=pages, coverage=coverage))
            await plan_activity(self.execution, f'read:{chapter.id}', localized_message(
                '已读第 {p0}/{p1} 章', p0=index + 1, p1=len(ids)), detail=chapter.name)
        return chapters

    async def excerpts(self, selections, chapters, *, strict_refs=False):
        resolve_plan_references(selections, chapters, strict=strict_refs)
        versions = {item.chapter_id: item.version for item in chapters}
        excerpts = []
        seen = set()
        for selection in selections:
            key = (selection.chapter_id, selection.start, selection.end)
            if key in seen:
                continue
            seen.add(key)
            chapter = await Chapter.get_or_none(id=selection.chapter_id, novel_id=self.novel_id)
            if chapter is None or versions.get(chapter.id) != chapter_version(chapter):
                raise ValueError(localized_message('选段原文未完整阅读或版本已变化'))
            if not 0 <= selection.start < selection.end <= len(chapter.production_text):
                raise ValueError(localized_message('选段位置超出原文范围'))
            if selection.quote and chapter.production_text[selection.start:selection.end] != selection.quote:
                raise ValueError(localized_message('方案选段与原文引文不一致'))
            excerpts.append(SourceExcerpt(**selection.model_dump(), text=chapter.production_text[selection.start:selection.end]))
        return excerpts
