import time
from typing import List
from openai import AsyncOpenAI

from models.chapter import Chapter
from models.asset import Asset
from models.scene import Scene
from prompts.storyboard import format_storyboard_prompt
from services.ai_task_executor import BaseTaskHandler
from services.storyboard.generator import generate_storyboard
from schemas.scene import SceneEntity
from utils.enums import AssetTypeEnum
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
        prompt_language = normalize_prompt_language(request_params.get("prompt_language"))

        # 1. 获取章节和相关资产
        chapter = await Chapter.get(id=chapter_id).prefetch_related("novel")
        all_assets = await Asset.filter(novel_id=chapter.novel_id)
        assets = [a for a in all_assets if chapter.number in (a.source_chapters or [])]

        # 2. 构建实体上下文
        entities = [
            SceneEntity(
                name=asset.canonical_name,
                aliases=asset.aliases or [],
                description=asset.description or asset.base_traits or "",
                asset_type=AssetTypeEnum(asset.asset_type).nickname,
            )
            for asset in assets
            if AssetTypeEnum(asset.asset_type)
            in (AssetTypeEnum.person, AssetTypeEnum.scene, AssetTypeEnum.item)
        ]

        # 3. 调用 OpenAI API 生成分镜
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
            )

            # 5. 返回结果
            return {
                "chapter_id": chapter_id,
                "scenes_created": len(scenes_created),
                "scene_ids": [s.id for s in scenes_created],
                "total_shots": len(storyboard.shots),
                "request_duration": round(request_duration, 2),
                "token_usage": api_metadata.get("usage", {}),
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
    ) -> List[Scene]:
        """将生成的分镜保存到数据库，并在 metadata 中存储元数据"""
        scenes_created = []

        for shot in storyboard.shots:
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
                "dialogue": shot.dialogue,
                "transition": shot.transition,
                "allowed_effects": shot.allowed_effects,
            }

            # 解析 duration 为浮点数
            duration_value = float(shot.duration.replace("s", ""))

            # 构建 metadata，包含 API 元数据
            scene_metadata = {
                "shot_title": shot.description,
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
            }

            # 如果有拒绝信息，添加到 metadata
            if "refusal" in api_metadata:
                scene_metadata["refusal"] = api_metadata["refusal"]
            prompt = format_storyboard_prompt(
                shot,
                prompt_language,
                entities=entities or [],
            )
            # 创建 Scene 记录
            scene = await Scene.create(
                chapter_id=chapter_id,
                sequence=shot.sequence,
                description=shot.description,
                prompt_params=prompt_params,
                prompt=prompt,
                duration=duration_value,
                metadata=scene_metadata
            )

            scenes_created.append(scene)

        return scenes_created
