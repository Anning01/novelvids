"""Compact wire format for shots of one short source. The saved format is RemakeShot."""
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from typing import Annotated, ClassVar

from schemas.agent_workflow import RemakeReference, RemakeShot

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ShotLook(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visual_style: Text
    format_and_look: Text
    lenses_and_filtration: Text
    lighting_and_atmosphere: Text
    grade_and_palette: Text
    effect_restrictions: list[str]


class ShortShot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sequence: int = Field(ge=1)
    look: int = Field(ge=1, description="1-based index in looks")
    description: Text
    shot_size_and_camera: Text
    time_setting: Text
    environment: Text
    spatial_relationships: Text
    visual_prose: Text
    actions: list[Text] = Field(min_length=1)
    camera_movement: Text
    sound_design: Text
    narration: list[str]
    dialogue: list[str]
    transition: Text
    asset_refs: list[RemakeReference]


class RemakeShortStoryboard(BaseModel):
    shot_type: ClassVar[type[RemakeShot]] = RemakeShot
    model_config = ConfigDict(extra="forbid")
    looks: list[ShotLook] = Field(min_length=1)
    shots: list[ShortShot] = Field(min_length=1)

    def materialize(self, intervals):
        expected = {item["sequence"]: item for item in intervals}
        indices = [shot.sequence for shot in self.shots]
        if len(indices) != len(expected) or set(indices) != set(expected):
            raise ValueError("Shot numbers do not match the source intervals")
        result = {}
        for shot in self.shots:
            if shot.look > len(self.looks):
                raise ValueError("Unknown shot look")
            span = expected[shot.sequence]
            value = self.shot_type.model_validate({
                **self.looks[shot.look - 1].model_dump(), **shot.model_dump(exclude={"look"}),
                "duration": f"{span['output_seconds']}s" if "output_seconds" in span else f"{span['end_seconds'] - span['start_seconds']:.6f}s",
            })
            if len({ref.asset_id for ref in value.asset_refs}) != len(value.asset_refs):
                raise ValueError("Shot-local asset IDs must be unique")
            result[shot.sequence] = value.model_dump(mode="json")
        return result
