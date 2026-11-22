"""Timeline output with optional visible design details. Keep the receipt names stable."""
from pydantic import Field

from schemas.agent_workflow import RemakeReference
from schemas.remake_timeline import RemakeShot as TimelineShot, RemakeShortStoryboard as TimelineBatch, ShortTimelineShot


class VisibleReference(RemakeReference):
    visual_description: str = Field(default="", description="Visible setting or prop details for the asset library")


class RemakeShot(TimelineShot):
    asset_refs: list[VisibleReference] = Field(max_length=30)


class ShortVisibleShot(ShortTimelineShot):
    asset_refs: list[VisibleReference]


class RemakeShortStoryboard(TimelineBatch):
    shot_type = RemakeShot
    shots: list[ShortVisibleShot] = Field(min_length=1)
