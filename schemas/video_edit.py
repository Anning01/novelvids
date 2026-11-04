"""Versioned, executable edit data. No paths, commands, markup or filter DSL."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class EditModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class EditSource(EditModel):
    kind: Literal['video', 'asset', 'library', 'missing']
    id: int = Field(gt=0)


class ClipBase(EditModel):
    id: str = Field(min_length=1, max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')
    name: str = Field(default='', max_length=255)
    start: float = Field(ge=0, le=86400)
    duration: float = Field(ge=1/60, le=86400)


class VideoClip(ClipBase):
    type: Literal['video']
    source: EditSource
    trim_in: float = Field(0, ge=0, le=86400)
    speed: float = Field(1, ge=.1, le=20)
    volume: float = Field(1, ge=0, le=10)
    scale: float = Field(1, ge=.1, le=4)
    fit: Literal['contain', 'cover'] = 'contain'
    rotation: float = Field(0, ge=-180, le=180)


class AudioClip(ClipBase):
    type: Literal['audio']
    source: EditSource
    trim_in: float = Field(0, ge=0, le=86400)
    volume: float = Field(1, ge=0, le=10)
    fade_in: float = Field(0, ge=0, le=86400)
    fade_out: float = Field(0, ge=0, le=86400)
    loop: bool = False

    @model_validator(mode='after')
    def fades_fit(self):
        if max(self.fade_in, self.fade_out) > self.duration:
            raise ValueError('Fade duration exceeds clip duration')
        return self


class SubtitleClip(ClipBase):
    type: Literal['subtitle']
    text: str = Field(max_length=2000)
    font: Literal['sans'] = 'sans'
    font_size: float = Field(42, ge=12, le=160)
    color: str = Field('#ffffff', pattern=r'^#[a-fA-F0-9]{6}$')
    bottom: float = Field(10, ge=0, le=100)
    x: float = Field(50, ge=0, le=100)
    bold: bool = False
    italic: bool = False
    underline: bool = False
    letter_spacing: float = Field(0, ge=-5, le=50)
    line_spacing: float = Field(0, ge=0, le=100)
    align: Literal['left', 'center', 'right'] = 'center'
    opacity: float = Field(1, ge=0, le=1)
    stroke_color: str = Field('#000000', pattern=r'^#[a-fA-F0-9]{6}$')
    stroke_width: float = Field(2, ge=0, le=10)
    shadow: float = Field(1, ge=0, le=10)


class StickerClip(ClipBase):
    type: Literal['sticker']
    source: EditSource
    x: float = Field(50, ge=0, le=100)
    y: float = Field(50, ge=0, le=100)
    scale: float = Field(1, ge=.1, le=4)
    opacity: float = Field(1, ge=0, le=1)
    scale_y: float | None = Field(None, ge=.1, le=4)
    lock_aspect: bool = True
    rotation: float = Field(0, ge=-180, le=180)


EditClip = Annotated[VideoClip | AudioClip | SubtitleClip | StickerClip, Field(discriminator='type')]


class EditDocument(EditModel):
    version: Literal[1] = 1
    width: int = Field(1280, ge=64, le=3840, multiple_of=2)
    height: int = Field(720, ge=64, le=3840, multiple_of=2)
    fps: Literal[24, 25, 30, 60] = 24
    clips: list[EditClip] = Field(default_factory=list, max_length=500)

    @model_validator(mode='after')
    def valid_timeline(self):
        if self.width * self.height > 3840 * 2160:
            raise ValueError('Canvas exceeds 4K')
        ids = [clip.id for clip in self.clips]
        if len(ids) != len(set(ids)):
            raise ValueError('Clip IDs must be unique')
        for clip in self.clips:
            clip.start = round(clip.start * self.fps) / self.fps
            clip.duration = max(1, round(clip.duration * self.fps)) / self.fps
        videos = sorted((c for c in self.clips if c.type == 'video'), key=lambda c: c.start)
        if any(a.start + a.duration > b.start + .001 for a, b in zip(videos, videos[1:])):
            raise ValueError('Main video clips cannot overlap')
        return self


class EditSave(EditModel):
    revision: int = Field(ge=0)
    document: EditDocument


class EditExportIn(EditModel):
    revision: int = Field(ge=1)


class EditLibraryIn(EditModel):
    resource_id: int = Field(gt=0)
