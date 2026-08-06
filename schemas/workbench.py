from pydantic import BaseModel, Field

from schemas.asset import AssetWithVariantsOut
from schemas.chapter import ChapterOut
from schemas.scene import SceneOut
from schemas.video import VideoOut


class WorkbenchPromptReferenceLimits(BaseModel):
    image: int = 9
    video: int = 3
    audio: int = 3


class WorkbenchPromptEditorOut(BaseModel):
    editor_key: str
    node_kind: str
    field_key: str
    label: str
    placeholder: str
    hint: str
    allowed_asset_types: list[str] | None = None
    excluded_asset_types: list[str] | None = None
    reference_limits: WorkbenchPromptReferenceLimits
    allow_prompt_injection: bool


class WorkbenchRefreshPolicyOut(BaseModel):
    poll_interval_ms: int = 1500
    poll_max_interval_ms: int = 12000


class WorkbenchCapabilitiesOut(BaseModel):
    """创作画布在当前部署中可执行的真实能力。"""

    upload_media: bool = True
    generate_asset: bool = True
    generate_video: bool = True
    apply_watermark: bool = False
    compose_video: bool = False
    prompt_editors: list[WorkbenchPromptEditorOut] = Field(
        default_factory=lambda: [
            WorkbenchPromptEditorOut(
                editor_key="asset_prompt",
                node_kind="asset",
                field_key="prompt",
                label="图片 Prompt",
                placeholder="描述希望生成的主体、场景、光线与画面风格",
                hint="输入 @ 引用已连接的参考图片",
                excluded_asset_types=[
                    "watermark",
                    "image",
                    "video",
                    "background_audio",
                    "sound_effect",
                ],
                reference_limits=WorkbenchPromptReferenceLimits(
                    image=10,
                    video=0,
                    audio=0,
                ),
                allow_prompt_injection=False,
            ),
            WorkbenchPromptEditorOut(
                editor_key="shot_prompt",
                node_kind="shot",
                field_key="prompt",
                label="镜头画面 Prompt",
                placeholder="描述镜头主体、动作、环境、运镜与节奏",
                hint="输入 @ 引用已连接的图片、视频、音频或文字素材",
                reference_limits=WorkbenchPromptReferenceLimits(),
                allow_prompt_injection=True,
            ),
        ]
    )
    refresh_policy: WorkbenchRefreshPolicyOut = Field(
        default_factory=WorkbenchRefreshPolicyOut
    )


class WorkbenchBootstrapOut(BaseModel):
    """当前章节画布所需的完整工作集，避免前端逐条请求详情。"""

    chapter: ChapterOut
    assets: list[AssetWithVariantsOut]
    scenes: list[SceneOut]
    videos: dict[int, list[VideoOut]]
