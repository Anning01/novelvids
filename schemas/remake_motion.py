"""Source observations for new remake jobs. Class names keep the existing durable receipt keys."""
from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.agent_workflow import RemakeShot as LegacyShot
from schemas.remake_short import RemakeShortStoryboard as LegacyBatch, ShortShot, Text


class RestartEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    at: float = Field(ge=0, description="Absolute source second of the reset or new start")
    seen: Text = Field(description="What visibly establishes the reset, second start or intentional replay")


class ActionView(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    key: Text = Field(description="Stable actor / physical action / object, identical across camera angles")
    onset: float = Field(ge=0, description="Original source second when this physical performance started")
    start: float = Field(ge=0, description="Absolute source start of this view")
    end: float = Field(gt=0, description="Absolute source end of this view")
    movement: Text = Field(description="Action initially performed, including framing when relevant")
    continuation: Text = Field(description="Only the visible remaining motion or held state and new framing")
    restart: RestartEvidence | None = Field(default=None, description="Only for an actual repetition, otherwise null")


class SoundCue(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    start: float = Field(ge=0, description="Absolute source seconds")
    end: float = Field(gt=0)
    sound: Text


class SourceSound(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ambience: Text = Field(description="Background audio or silence, without timecodes")
    cues: list[SoundCue] = Field(default_factory=list)


class SoundFields:
    @model_validator(mode="before")
    @classmethod
    def unpack_shot_fields(cls, data):
        if not isinstance(data, dict) or not isinstance(sound := data.get("sound_design"), dict):
            return data
        nested = sound.keys() & {"last_visible_state", "transition", "dialogue", "narration", "asset_refs"}
        if not nested:
            return data
        # Repair a misplaced closing brace only when the two locations agree.
        if any(key in data and data[key] != sound[key] for key in nested):
            return data
        return {**data, **{key: sound[key] for key in nested},
                "sound_design": {k: v for k, v in sound.items() if k not in nested}}


class RemakeShot(SoundFields, LegacyShot):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    transition: Text = Field(alias="last_visible_state", description="Physical state in the last visible frame of this interval")
    sound_design: SourceSound
    actions: list[ActionView] = Field(min_length=1)


class ShortMotionShot(SoundFields, ShortShot):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    transition: Text = Field(alias="last_visible_state", description="Physical state in the last visible frame of this interval")
    sound_design: SourceSound
    actions: list[ActionView] = Field(min_length=1)


class RemakeShortStoryboard(LegacyBatch):
    shot_type = RemakeShot
    shots: list[ShortMotionShot] = Field(min_length=1)

def shot_contracts(params):
    if params.get("remake_action_memory") == "timeline":
        from schemas.remake_timeline import RemakeShot as TimelineShot, RemakeShortStoryboard as TimelineBatch
        return TimelineShot, TimelineBatch
    if params.get("remake_action_memory"):
        return RemakeShot, RemakeShortStoryboard
    return LegacyShot, LegacyBatch
