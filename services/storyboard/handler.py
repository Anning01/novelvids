
from utils.messages import localized_message
import time
from typing import List
from openai import AsyncOpenAI

from models.chapter import Chapter
from models.asset import Asset
from models.scene import Scene
from prompts.storyboard import (
    format_storyboard_prompt,
    normalized_storyboard_reference_fields,
    referenced_entities,
)
from services.ai_task_executor import BaseTaskHandler
from services.storyboard.generator import generate_storyboard
from services.storyboard.strategies import storyboard_strategy_factory
from services.storyboard.validation import validate_storyboard_duration
from services.storyboard.entities import generation_entities_for_assets, shot_variant_bindings
from services.storyboard.appearances import previously_seen_assets
from services.creation_agent.memory import creation_memory
from services.creation_objects import CreationObjects, project_write
from schemas.scene import SceneEntity
from utils.prompt_language import normalize_prompt_language


class StoryboardTaskHandler(BaseTaskHandler):
    """Sora 2 超详细分镜生成任务处理器"""

    async def execute(self, request_params: dict) -> dict:
        """
        request_params:
            chapter_id: int - 章节ID
            base_url: str - API基础URL
            api_key: str - API密钥
            model: str - 模型名称
            supports_json_output: bool - 是否支持 response_format=json_object
        """
        chapter_id = request_params["chapter_id"]
        base_url = request_params["base_url"]
        api_key = request_params["api_key"]
        model = request_params["model"]
        supports_json_output = request_params.get("supports_json_output", False)
        max_context_characters = request_params.get("max_context_characters")
        thinking = request_params.get("thinking")
        max_tokens = request_params.get("max_tokens")
        prompt_language = normalize_prompt_language(request_params.get("prompt_language"))

        # 1. 获取章节和相关资产
        chapter = await Chapter.get(id=chapter_id).prefetch_related("novel")
        strategy = storyboard_strategy_factory.resolve(
            request_params.get("storyboard_strategy")
            or chapter.novel.storyboard_strategy
        )
        all_assets = await Asset.filter(novel_id=chapter.novel_id)
        assets = [a for a in all_assets if chapter.number in (a.source_chapters or [])]
        from services.creation_agent.step_context import context_assets
        additional_assets = await context_assets(request_params)
        assets = list({asset.id: asset for asset in [*assets, *additional_assets]}.values())

        # 2. 构建实体上下文
        from services.creation_agent.step_context import step_context
        plan_context = await step_context(request_params)
        selected = {}
        if plan_context:
            from models.asset_variant import AssetVariant
            selected = {row.asset_id: row.id for row in await AssetVariant.filter(id__in=plan_context.step.variant_ids)}
        loaded = await Asset.filter(id__in=[asset.id for asset in assets]).prefetch_related('variants')
        entities = generation_entities_for_assets(loaded, chapter.number, selected)

        # 3. 调用 OpenAI API 生成分镜
        creative_constraints = await creation_memory.for_generation(chapter, assets)
        seen_assets = await previously_seen_assets(chapter, entities)
        start_time = time.time()

        try:
            client = AsyncOpenAI(base_url=base_url, api_key=api_key)
            
            storyboard, api_metadata = await generate_storyboard(
                client=client,
                long_text=chapter.content,
                entities=entities,
                model=model,
                supports_json_output=supports_json_output,
                prompt_language=prompt_language,
                max_context_characters=max_context_characters,
                thinking=thinking,
                max_tokens=max_tokens,
                storyboard_strategy=strategy.key,
                creative_constraints=creative_constraints,
                previously_seen_assets=seen_assets,
                introduction_descriptions={asset.canonical_name: asset.description or "" for asset in assets},
            )

            end_time = time.time()
            request_duration = end_time - start_time

            # 4. 保存分镜到数据库
            scenes_created = await self._save_scenes(
                chapter_id=chapter_id,
                storyboard=storyboard,
                api_metadata=api_metadata,
                request_duration=request_duration,
                prompt_language=prompt_language,
                entities=entities,
                storyboard_strategy=strategy.key,
            )

            from services.creation_agent.skill_execution import current_execution
            from models.agent_operation import AgentOperation
            execution = current_execution.get()
            review = await AgentOperation.get_or_none(task_id=execution.params['task_id'],
                key='creative-review:storyboard', state='completed') if execution else None
            notes = review.result.get('notes', []) if review else []

            # 5. 返回结果
            return {
                "chapter_id": chapter_id,
                "scenes_created": len(scenes_created),
                "scene_ids": [s.id for s in scenes_created],
                "total_shots": len(storyboard.shots),
                "request_duration": round(request_duration, 2),
                "token_usage": api_metadata.get("usage", {}),
                **({'needs_revision': True, 'review_notes': notes} if notes else {}),
            }

        except Exception as e:
            end_time = time.time()
            request_duration = end_time - start_time
            raise Exception(f"分镜生成失败 (耗时 {request_duration:.2f}s): {str(e)}") from e

    async def _save_scenes(
        self,
        chapter_id: int,
        storyboard,
        api_metadata: dict,
        request_duration: float,
        prompt_language: str = "zh",
        entities: list[SceneEntity] | None = None,
        storyboard_strategy: str | None = None,
    ) -> List[Scene]:
        """将生成的分镜保存到数据库，并在 metadata 中存储元数据"""
        chapter = await Chapter.get(id=chapter_id)
        from services.creation_agent.skill_execution import current_execution
        from services.creation_agent.operation_receipts import execute_step
        execution = current_execution.get()
        if execution:
            # Validate all candidate shots before any persistent changes.
            from services.creation_agent.prompt_edits import validate_prompt_dependencies
            from services.creation_agent.operations import CreationOperations
            from services.storyboard.validation import validate_skill_storyboard_shot
            from services.storyboard.speech_timing import StoryboardSpeechValidator
            issues = StoryboardSpeechValidator(execution.snapshot).continuity_issues(storyboard.shots, entities or [])
            if issues:
                raise ValueError(issues[0][1])
            for shot in storyboard.shots:
                validate_storyboard_duration(shot, execution.params.get("shot_duration_range"))
                validate_skill_storyboard_shot(shot, execution.snapshot, prompt_language, entities or [])
                validate_prompt_dependencies(shot.prompt, entities or [])
                CreationOperations.validate_timing(shot.prompt, float(shot.duration.removesuffix('s')))
            async def persist():
                async with project_write(chapter.novel_id):
                    from services.creation_agent.step_context import validate_step_inputs
                    await validate_step_inputs(execution.params)
                    from models.ai_task import AiTask
                    from services.creation_agent.object_state import object_version
                    task = await AiTask.get(id=execution.params['task_id'])
                    before = execution.params.get('replace_versions')
                    if before is not None:
                        old_scenes = await Scene.filter(chapter_id=chapter.id).order_by('sequence')
                        if {str(row.id): await object_version(row) for row in old_scenes} != before:
                            raise ValueError(localized_message('原分镜已有新修改，请核对后重新生成'))
                        objects = CreationObjects(chapter.novel_id)
                        snapshots = {str(row.id): await objects.archive('scene', row.id, current_storyboard_task=task) for row in reversed(old_scenes)}
                        task.request_params = {**task.request_params, 'replaced_scene_snapshots': snapshots}
                        await task.save(update_fields=['request_params'])
                    rows = await self._persist_scenes(chapter, storyboard, api_metadata, request_duration,
                        prompt_language, entities, storyboard_strategy)
                    return {'scene_ids': [row.id for row in rows]}
            result = await execute_step(execution.params['task_id'], 'persist:storyboard', persist, atomic=True)
            return await Scene.filter(id__in=result['scene_ids']).order_by('sequence')
        async with project_write(chapter.novel_id):
            return await self._persist_scenes(chapter, storyboard, api_metadata, request_duration,
                                              prompt_language, entities, storyboard_strategy)

    async def _persist_scenes(self, chapter: Chapter, storyboard, api_metadata: dict, request_duration: float,
                             prompt_language: str, entities: list[SceneEntity] | None, storyboard_strategy: str | None) -> List[Scene]:
        from services.creation_agent.skill_execution import current_execution
        execution = current_execution.get()
        objects = CreationObjects(chapter.novel_id)
        scenes_created = []
        strategy = storyboard_strategy_factory.resolve(storyboard_strategy)
        for shot in storyboard.shots:
            normalized = shot.model_copy(update=normalized_storyboard_reference_fields(shot, entities or []))
            bindings = shot_variant_bindings(normalized, entities or [])
            await objects.validate_variant_bindings([int(key) for key in bindings], bindings)

        for shot in storyboard.shots:
            original_description = shot.description
            reference_updates = normalized_storyboard_reference_fields(
                shot,
                entities or [],
            )
            if reference_updates:
                shot = shot.model_copy(update=reference_updates)

            # 构建 prompt JSON 对象
            prompt_params = {
                "shot_size_and_camera": shot.shot_size_and_camera,
                "visual_style": shot.visual_style,
                "effect_restrictions": shot.effect_restrictions,
                "time_setting": shot.time_setting,
                "environment": shot.environment,
                "spatial_relationships": shot.spatial_relationships,
                "visual_prose": shot.visual_prose,
                "actions": shot.actions,
                "format_and_look": shot.format_and_look,
                "lenses_and_filtration": shot.lenses_and_filtration,
                "lighting_and_atmosphere": shot.lighting_and_atmosphere,
                "grade_and_palette": shot.grade_and_palette,
                "camera_movement": shot.camera_movement,
                "sound_design": shot.sound_design,
                "narration": shot.narration,
                "dialogue": shot.dialogue,
                "transition": shot.transition,
                "allowed_effects": shot.allowed_effects,
            }

            # 解析 duration 为浮点数
            if shot.segments:
                prompt_params["segments"] = [segment.model_dump() for segment in shot.segments]
            if shot.reference_only_types:
                prompt_params["reference_only_types"] = list(shot.reference_only_types)
            duration_value = float(shot.duration.replace("s", ""))

            # 构建 metadata，包含 API 元数据
            scene_metadata = {
                "shot_title": original_description,
                "duration_str": shot.duration,
                "sequence_id": shot.sequence,
                # API 调用元数据
                "api_metadata": {
                    "model": api_metadata.get("model"),
                    "response_id": api_metadata.get("response_id"),
                    "created": api_metadata.get("created"),
                    "system_fingerprint": api_metadata.get("system_fingerprint"),
                },
                # Token 使用情况
                "token_usage": api_metadata.get("usage", {}),
                # 请求参数
                "request_duration": round(request_duration, 2),
                "prompt_language": normalize_prompt_language(prompt_language),
                "generation_batch_count": api_metadata.get("batch_count", 1),
                "storyboard_strategy": strategy.key,
                "storyboard_strategy_name": strategy.name,
            }

            # 如果有拒绝信息，添加到 metadata
            if "refusal" in api_metadata:
                scene_metadata["refusal"] = api_metadata["refusal"]
            from utils.prompt_language import skill_workflow
            if skill_workflow.get():
                from services.creation_agent.prompt_edits import validate_prompt_dependencies
                from services.creation_agent.operations import CreationOperations
                prompt = shot.prompt
                validate_prompt_dependencies(prompt, entities or [])
                CreationOperations.validate_timing(prompt, duration_value)
                prompt_params['prompt_language'] = prompt_language
                prompt_params['rendering_version'] = 'agent-skills-v1'
                if execution and "storyboard_contract" in execution.snapshot.contents:
                    import json
                    prompt_params['prompt_contract_version'] = json.loads(execution.snapshot.read("storyboard_contract"))["version"]
            else:
                prompt = format_storyboard_prompt(
                    shot,
                    prompt_language,
                    entities=entities or [],
                    strategy=strategy,
                )
            # 镜头实际引用的资产 ID，持久化到 scene.assets（与画布工作流共用同一份引用数据）
            referenced_asset_ids = list(dict.fromkeys(
                entity.asset_id
                for entity in referenced_entities(shot, entities or [])
                if entity.asset_id is not None
            ))

            # 创建 Scene 记录
            scene = await objects.create_scene(chapter.id, after_id=None, values=dict(
                description=original_description,
                prompt_params=prompt_params,
                prompt=prompt,
                duration=duration_value,
                metadata=scene_metadata
            ))
            await objects.bind_assets(scene, referenced_asset_ids)
            bindings = shot_variant_bindings(shot, entities or [])
            if bindings:
                scene.metadata = {**scene.metadata, 'asset_variant_ids': bindings}
                await scene.save(update_fields=['metadata'])

            scenes_created.append(scene)

        return scenes_created
