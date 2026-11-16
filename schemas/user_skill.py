from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

TextTask = Literal['story', 'screenplay', 'assets', 'storyboard']


class SkillReference(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=32000)


class UserSkillInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    task: TextTask
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default='', max_length=1000)
    instructions: str = Field(min_length=1, max_length=32000)
    references: list[SkillReference] = Field(default_factory=list, max_length=10)
    is_active: bool = True


class UserSkillUpdate(UserSkillInput):
    expected_version: int = Field(ge=1)


class SkillPreferenceInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    skill_id: int = Field(ge=0)
