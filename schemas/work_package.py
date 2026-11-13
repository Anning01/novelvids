"""Portable authoring package v1; stable IDs never encode database IDs or order."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Identity(StrictModel):
    id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$')
    name: str = Field(min_length=1, max_length=100)


class Episode(StrictModel):
    format_version: Literal[1]
    work: Identity
    episode: Identity
    number: int = Field(ge=1)
    aspect_ratio: Literal['16:9', '9:16', '1:1', '4:3', '3:4'] = '16:9'
    style_key: str | None = Field(None, max_length=64)
    custom_style_prompt: str | None = Field(None, max_length=2000)
    storyboard_enabled: bool | None = None
    language: Literal['zh', 'en'] = 'zh'
    screenplay: str = 'screenplay.md'
    source_text: str | None = None
    assets: str = 'assets.json'
    storyboard: str = 'storyboard.json'
    originals: list[str] = Field(default_factory=list)


class Media(StrictModel):
    path: str
    role: Literal['main', 'angle_1', 'angle_2', 'reference', 'video', 'audio', 'blocking', 'storyboard']


class Variant(Identity):
    description: str = ''
    prompt: str = Field(min_length=1)
    media: list[Media] = Field(default_factory=list)


class PackageAsset(Variant):
    kind: Literal['person', 'group', 'scene', 'item']
    aliases: list[str] = Field(default_factory=list)
    variants: list[Variant] = Field(default_factory=list)


class VisualReference(StrictModel):
    asset_id: str
    variant_id: str | None = None


class Voice(StrictModel):
    asset_id: str
    mode: Literal['dialogue', 'offscreen', 'os', 'narration']
    text: str = Field(min_length=1)
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)


class Shot(Identity):
    scene_id: str
    description: str = Field(min_length=1)
    duration: float = Field(gt=0, le=3600, allow_inf_nan=False)
    prompt: str = ''
    structure: dict = Field(default_factory=dict)
    # Eight-column and specialized authoring remain verbatim, not re-rendered.
    drafts: dict[str, str] = Field(default_factory=dict)
    visual: list[VisualReference] = Field(default_factory=list)
    voices: list[Voice] = Field(default_factory=list)
    media: list[Media] = Field(default_factory=list)

    @model_validator(mode='after')
    def check_timing(self):
        sheet = self.structure.get("storyboard_sheet")
        if sheet is not None and (not isinstance(sheet, dict) or any(
            key in sheet and not isinstance(sheet[key], str) for key in ("video_guidance", "video_prompt", "image_prompt")
        )):
            raise ValueError("故事版提示词须使用文本")
        for role in ("storyboard", "blocking"):
            if sum(m.role == role for m in self.media) > 1:
                raise ValueError("每镜每类制作图只登记一张")
        if any(v.end <= v.start or v.end > self.duration for v in self.voices):
            raise ValueError('人声时间轴超出镜头时长')
        if len({r.asset_id for r in self.visual}) != len(self.visual):
            raise ValueError('出镜资产重复')
        return self


class Assets(StrictModel):
    assets: list[PackageAsset]


class Storyboard(StrictModel):
    scenes: list[Identity]
    shots: list[Shot]


class ImportEpisode(StrictModel):
    directory: str
    request_id: str = Field(min_length=1, max_length=120)
    confirmed: Literal[True]


class UpdateShot(StrictModel):
    directory: str
    request_id: str = Field(min_length=1, max_length=120)
    confirmed: Literal[True]
    work_id: str
    episode_id: str
    shot_id: str
    base_version: str
    changes: dict = Field(min_length=1)


class ReadEpisode(StrictModel):
    work_id: str
    episode_id: str
    shot_id: str | None = None
