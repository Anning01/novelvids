"""New jobs return the text to save, with source times for display in the editor."""
from pydantic import BaseModel, ConfigDict, Field

from schemas.remake_motion import RemakeShot as MotionShot, ShortMotionShot
from schemas.remake_short import RemakeShortStoryboard as BaseBatch, Text


class TimedAction(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: Text


class RemakeShot(MotionShot):
    actions: list[TimedAction] = Field(min_length=1)


class ShortTimelineShot(ShortMotionShot):
    actions: list[TimedAction] = Field(min_length=1)


class RemakeShortStoryboard(BaseBatch):
    shot_type = RemakeShot
    shots: list[ShortTimelineShot] = Field(min_length=1)
