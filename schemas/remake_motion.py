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

    @model_validator(mode="after")
    def ordered_times(self):
        if self.end <= self.start or self.onset >= self.end:
            raise ValueError("Each view must end after its start and the physical action onset")
        if self.restart and self.restart.at > self.onset:
            raise ValueError("Reset evidence cannot follow the new onset")
        return self


class SoundCue(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    start: float = Field(ge=0, description="Absolute source seconds")
    end: float = Field(gt=0)
    sound: Text

    @model_validator(mode="after")
    def ordered_times(self):
        if self.end <= self.start:
            raise ValueError("A sound cue must have a positive duration")
        return self


class SourceSound(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ambience: Text = Field(description="Background audio or silence, without timecodes")
    cues: list[SoundCue] = Field(default_factory=list)


class RemakeShot(LegacyShot):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    transition: Text = Field(alias="last_visible_state", description="Physical state in the last visible frame of this interval")
    sound_design: SourceSound
    actions: list[ActionView] = Field(min_length=1)


class ShortMotionShot(ShortShot):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    transition: Text = Field(alias="last_visible_state", description="Physical state in the last visible frame of this interval")
    sound_design: SourceSound
    actions: list[ActionView] = Field(min_length=1)


class RemakeShortStoryboard(LegacyBatch):
    shot_type = RemakeShot
    shots: list[ShortMotionShot] = Field(min_length=1)

    def materialize(self, intervals):
        rows = super().materialize(intervals)
        for span in intervals:
            views = rows[span["sequence"]]["actions"]
            if not any(v["start"] < span["end_seconds"] and span["start_seconds"] < v["end"] for v in views):
                raise ValueError("No observed action view overlaps its assigned source interval")
        return rows


def shot_contracts(params):
    if params.get("remake_action_memory"):
        return RemakeShot, RemakeShortStoryboard
    return LegacyShot, LegacyBatch
