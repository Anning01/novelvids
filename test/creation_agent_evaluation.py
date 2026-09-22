"""Fixed synthetic evaluation inputs and evidence collection through production tasks.

This module never chooses a provider or opens a network client. The caller supplies
an existing test model configuration and controls provider/budget instrumentation.
"""

import copy
import hashlib
import json
import re
import time
from pathlib import Path
from importlib.metadata import version
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4
from unittest.mock import patch

from pydantic import BaseModel, ConfigDict, Field

from auth.deps import AuthContext
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.chapter import Chapter
from models.creation_agent import AgentMessage, AgentSettings, CreationConstraint, PromptChange
from models.novel import Novel
from models.scene import Scene
from prompts.storyboard import format_storyboard_prompt
from schemas.creation_agent import AgentConfiguration, AgentRunRequest, StoryboardVisualChanges
from schemas.scene import SceneEntity
from services.ai_task_executor import AiTaskExecutor
from services.billing.pricing import compute_text_cost
from services.creation_agent.handler import CreationAgentTaskHandler
from services.creation_agent.sessions import agent_sessions
from services.creation_agent.tools import PromptEditService
from test.test_services.test_storyboard_prompts import _shot
from utils.enums import AiTaskTypeEnum, TaskStatusEnum

CORPUS_PATH = Path(__file__).parent / 'fixtures/creation_agent/cases.json'


class EvaluationStep(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message: str
    targets: list[str]
    chapter: int = Field(1, ge=1, le=3)
    expected_outcome: Literal['edit', 'memory', 'clarify', 'refuse']
    expected_segments: dict[str, int] = Field(default_factory=dict)
    new_conversation: bool = False


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    group: Literal['image', 'storyboard', 'scope']
    title: str
    steps: list[EvaluationStep]
    initial_prompts: dict[str, str | None] = Field(default_factory=dict)
    legacy_scenes: list[str] = Field(default_factory=list)
    review: list[str]
    memory_policy: Literal['none', 'targets', 'project', 'chapter', 'chapter_or_range']


def load_cases() -> list[EvaluationCase]:
    return [EvaluationCase.model_validate(item) for item in json.loads(CORPUS_PATH.read_text())['cases']]


async def create_evaluation_project(case: EvaluationCase):
    """Three chapters × four independently generated Scenes, four shared assets."""
    novel = await Novel.create(name=f'合成验收-{case.id}-{uuid4().hex[:8]}', total_chapters=3,
        story_outline='第一章雨夜候车，第二章到值班室查记录，第三章林岚左手受伤并换雨衣。',
        project_setting='林岚锁定身份：黑色齐肩短发，瘦削脸型。周鸣：黑色短发、深蓝色夹克。')
    definitions = {
        'heroine': ('林岚', 1, '黑色齐肩短发，瘦削脸型，穿灰色粗纺风衣，左衣领有缺口，手持黑伞。'),
        'hero': ('周鸣', 1, '三十岁男子，黑色短发，深蓝色夹克，手持牛皮纸文件袋。'),
        'station': ('站台', 2, '旧站台，灰色水泥地面，绿色指示牌，冷白色顶灯，入口在画面左侧。'),
        'office': ('值班室', 2, '窄小值班室，木门、木桌与金属档案柜，窗户位于桌子右侧。'),
    }
    targets = {}
    assets = {}
    for key, (name, kind, description) in definitions.items():
        asset = await Asset.create(novel=novel, canonical_name=name, asset_type=kind,
            description=description, base_traits=description, main_image=f'synthetic/{key}.png')
        assets[key] = asset
        targets[key] = ('asset', asset.id)
    variant = await AssetVariant.create(asset=assets['heroine'], name='雨衣形态', chapter_numbers=[3],
        base_traits='黑色齐肩短发，瘦削脸型，穿蓝色长雨衣，左手缠白色绷带，手持黑伞。', images=['synthetic/raincoat.png'])
    targets['raincoat'] = ('variant', variant.id)
    chapters = {}
    for number in (1, 2, 3):
        chapter = await Chapter.create(novel=novel, number=number, name=f'第{number}章',
            content=f'第{number}章合成正文：林岚和周鸣在站台说话。' + ('林岚左手受伤并换上蓝色雨衣。' if number == 3 else '林岚尚未受伤，穿灰色风衣。'))
        chapters[number] = chapter.id
        entities = [SceneEntity(asset_id=asset.id, name=asset.canonical_name, aliases=[],
            asset_type='人物' if asset.asset_type == 1 else '场景',
            description=variant.base_traits if number == 3 and key == 'heroine' else asset.base_traits)
            for key, asset in assets.items()]
        for sequence in range(1, 5):
            label = chr(ord('A') + (number - 1) * 4 + sequence - 1)
            shot = _shot(sequence, f'{label}：林岚与周鸣候车').model_copy(update={
                'duration': '6s', 'visual_prose': '@{林岚}站在@{站台}中央，@{周鸣}站在右侧。',
                'spatial_relationships': '@{林岚}与@{周鸣}并肩面向入口，入口在左侧。',
                'actions': ['0s-6s: @{林岚}握伞站定，@{周鸣}看向入口。'],
                'dialogue': ['@{周鸣}：“车还没来。”'], 'narration': ['远处传来列车的声音。'],
                'sound_design': '雨声和远处列车声',
            })
            scene = await Scene.create(chapter=chapter, sequence=sequence, description=shot.description, duration=6,
                prompt_params=shot.model_dump(mode='json'), prompt=format_storyboard_prompt(shot, entities=entities),
                metadata={'synthetic': True})
            await scene.assets.add(*assets.values())
            targets[label] = ('scene', scene.id)
    for key, prompt in case.initial_prompts.items():
        kind, id = targets[key]
        if kind == 'scene':
            values = {'prompt': prompt}
            if key in case.legacy_scenes:
                values['prompt_params'] = {}
            await Scene.filter(id=id).update(**values)
        else:
            await (Asset if kind == 'asset' else AssetVariant).filter(id=id).update(base_traits=prompt)
    return novel, chapters, targets


async def business_snapshot(novel_id: int) -> dict:
    """All protected fields and references; only synthetic business data is exported."""
    groups = {
        'novel': await Novel.filter(id=novel_id).values(),
        'chapter': await Chapter.filter(novel_id=novel_id).order_by('id').values(),
        'asset': await Asset.filter(novel_id=novel_id).order_by('id').values(),
        'variant': await AssetVariant.filter(asset__novel_id=novel_id).order_by('id').values(),
        'scene': await Scene.filter(chapter__novel_id=novel_id).order_by('id').values(),
    }
    for rows in groups.values():
        for row in rows:
            row.pop('created_at', None)
            row.pop('updated_at', None)
    for row in groups['scene']:
        scene = await Scene.get(id=row['id'])
        row['asset_ids'] = await scene.assets.all().order_by('id').values_list('id', flat=True)
    return copy.deepcopy(groups)


def evaluate_invariants(before: dict, after: dict, allowed: set[tuple[str, int]], expected_segments: dict[int, int]) -> list[str]:
    """Structural checks only: semantic quality stays explicitly unreviewed."""
    failures = []
    for kind, rows in before.items():
        old_rows = {row['id']: row for row in rows}
        new_rows = {row['id']: row for row in after[kind]}
        if old_rows.keys() != new_rows.keys():
            failures.append(f'{kind}: object set changed')
        for id in old_rows.keys() & new_rows.keys():
            old, new = copy.deepcopy(old_rows[id]), copy.deepcopy(new_rows[id])
            if (kind, id) in allowed:
                if kind == 'scene':
                    old.pop('prompt', None); new.pop('prompt', None)
                    for params in (old.get('prompt_params') or {}, new.get('prompt_params') or {}):
                        for field in StoryboardVisualChanges.model_fields:
                            params.pop(field, None)
                elif kind in ('asset', 'variant'):
                    old.pop('base_traits', None); new.pop('base_traits', None)
            if old != new:
                failures.append(f'{kind}:{id}: protected fields changed')
    before_scenes = {row['id']: row for row in before['scene']}
    for row in after['scene']:
        if ('scene', row['id']) not in allowed:
            continue
        previous = before_scenes.get(row['id']) or {}
        if (previous.get('prompt'), previous.get('prompt_params')) == (row.get('prompt'), row.get('prompt_params')):
            # A declined/failed edit is an outcome failure. Existing legacy text
            # must not be misreported as data corruption caused by the agent.
            continue
        prompt = row.get('prompt') or ''
        if re.search(r'镜头\s*\d+\s*的(?:女生|男生|人物)|(?:服装|外貌|环境描述)\s*同上', prompt):
            failures.append(f"scene:{row['id']}: external shorthand")
        numbers = [int(n) for n in re.findall(r'【镜头(\d+)\s*·', prompt)]
        if numbers and numbers != list(range(1, len(numbers) + 1)):
            failures.append(f"scene:{row['id']}: nonlocal numbering")
        if row['id'] in expected_segments and len(numbers) != expected_segments[row['id']]:
            failures.append(f"scene:{row['id']}: incorrect segment count")
    return failures


def missing_current_definitions(target: dict) -> list[str]:
    # Asset names inside definitions also carry the renderer's reference markup.
    prompt = re.sub(r'@\{([^{}]+)\}', r'\1', target.get('prompt') or '')
    return [entity['name'] for entity in target['entities']
            if entity['name'] in prompt and entity['description'] not in prompt]


async def run_evaluation_case(case: EvaluationCase, model_config, repetition: int) -> dict:
    """Use actual session admission, executor, prompt writers, memory and billing."""
    from services.creation_agent import handler as handler_module

    novel, chapters, targets = await create_evaluation_project(case)
    await AgentSettings.update_or_create(id=1, defaults={'configuration': AgentConfiguration(enabled=True).model_dump()})
    conversation = await agent_sessions.create(novel.id, AuthContext())
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.creation_agent, CreationAgentTaskHandler())
    records = []
    for index, step in enumerate(case.steps):
        if step.new_conversation:
            conversation = await agent_sessions.create(novel.id, AuthContext())
        selected = {targets[key] for key in step.targets}
        request = AgentRunRequest(request_id=uuid4(), message=step.message, chapter_id=chapters[step.chapter],
            model_config_id=model_config.id, targets=[{'kind': kind, 'id': id} for kind, id in sorted(selected)])
        before = await business_snapshot(novel.id)
        task = await agent_sessions.submit(conversation, request, AuthContext())
        started = time.monotonic()
        first_event = None
        first_output = None
        stream = handler_module.stream_creation_agent

        async def measured_stream(**kwargs):
            nonlocal first_event, first_output
            async for event in stream(**kwargs):
                if first_event is None:
                    first_event = time.monotonic() - started
                if first_output is None and event.type in {'TEXT_MESSAGE_CONTENT', 'TOOL_CALL_START'}:
                    first_output = time.monotonic() - started
                yield event

        with patch.object(handler_module, 'stream_creation_agent', measured_stream):
            await executor.run(task)
        duration = time.monotonic() - started
        await task.refresh_from_db()
        assistant = await AgentMessage.get(task=task, role='assistant')
        after = await business_snapshot(novel.id)
        writable = selected if step.expected_outcome == 'edit' else set()
        failures = evaluate_invariants(before, after, writable,
            {targets[key][1]: value for key, value in step.expected_segments.items()})
        changes = await PromptChange.filter(task=task).order_by('id').values('changes')
        outcome_failures = []
        if step.expected_outcome == 'edit' and not changes:
            outcome_failures.append('No saved change for executable request')
        if task.status != TaskStatusEnum.completed.value:
            outcome_failures.append('Run did not complete')
        constraints = await CreationConstraint.filter(novel_id=novel.id).order_by('id').values('content', 'scope', 'source_quote', 'superseded_by_id')
        if case.memory_policy == 'none' and constraints:
            failures.append('One-off request became persistent memory')
        if step.expected_outcome == 'memory' and not constraints:
            outcome_failures.append('Explicit memory was not saved')
        allowed_memory_scopes = {'chapter', 'range'} if case.memory_policy == 'chapter_or_range' else {case.memory_policy}
        if any(row['scope']['kind'] not in allowed_memory_scopes for row in constraints):
            failures.append('Persistent memory scope differs from the fixed expected scope')
        current_targets = await PromptEditService(novel_id=novel.id, task_id=task.id,
            allowed_targets=selected, max_batch_size=8).read_targets()
        before_scenes = {row['id']: row for row in before['scene']}
        after_scenes = {row['id']: row for row in after['scene']}
        for target in current_targets:
            if target['kind'] != 'scene' or step.expected_outcome != 'edit':
                continue
            old, new = before_scenes.get(target['id'], {}), after_scenes.get(target['id'], {})
            if (old.get('prompt'), old.get('prompt_params')) == (new.get('prompt'), new.get('prompt_params')):
                continue
            for name in missing_current_definitions(target):
                failures.append(f"scene:{target['id']}: current definition missing for {name}")
        records.append({'step': index + 1, 'request': request.model_dump(mode='json'), 'status': task.status,
            'hard_failures': failures, 'outcome_failures': outcome_failures, 'before': before, 'after': after, 'changes': changes, 'constraints': constraints,
            'reply': assistant.content, 'events': assistant.events, 'usage': assistant.usage, 'current_targets': current_targets,
            'retry_prompts': sum(part.get('part_kind') == 'retry-prompt' for message in assistant.native_messages for part in message.get('parts', [])) if assistant.native_messages else None,
            'cost_cny': str(compute_text_cost(assistant.usage, model_config.pricing)) if not assistant.usage.get('missing_usage') else None,
            'first_event_seconds': first_event, 'first_output_seconds': first_output, 'duration_seconds': duration,
            'quality_review': {'reviewer': None, 'intent_fulfilled': None, 'intent': None, 'continuity': None, 'independent_use': None, 'reason': None}})
    return {'case_id': case.id, 'repetition': repetition, 'model': model_config.model,
            'provider_host': urlsplit(model_config.base_url).hostname,
            'model_parameters': {'max_tokens': min(3000, model_config.max_tokens or 3000),
                                 'thinking': model_config.thinking, 'configuration': AgentConfiguration(enabled=True).model_dump()},
            'runtime_versions': {package: version(package) for package in ('pydantic-ai-slim', 'ag-ui-protocol', 'openai')},
            'corpus_sha256': hashlib.sha256(CORPUS_PATH.read_bytes()).hexdigest(),
            'status': 'hard_failure' if any(record['hard_failures'] for record in records) else
                      'outcome_failure' if any(record['outcome_failures'] for record in records) else 'awaiting_quality_review',
            'steps': records}
