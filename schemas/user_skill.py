from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, AfterValidator
from schemas.chapter import EpisodePacing

TextTask = Literal['story', 'screenplay', 'assets', 'storyboard']


def nonblank_markdown(value: str) -> str:
    if not value.strip():
        raise ValueError('Markdown must not be blank')
    return value


Markdown = Annotated[str, StringConstraints(strip_whitespace=False, min_length=1, max_length=32000), AfterValidator(nonblank_markdown)]


class SkillReference(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    content: Markdown


class UserSkillInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    task: TextTask
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default='', max_length=1000)
    instructions: Markdown
    references: list[SkillReference] = Field(default_factory=list, max_length=10)
    is_active: bool = True


class UserSkillUpdate(UserSkillInput):
    expected_version: int = Field(ge=1)


class SkillPreferenceInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    skill_id: int = Field(ge=0)


class SkillTrialInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    skill: UserSkillInput
    model_config_id: int = Field(gt=0)
    input: str = Field(min_length=1, max_length=64000)
    episode_pacing: EpisodePacing = Field(default_factory=EpisodePacing)
    # None inherits the saved model preference; an empty value omits it.
    thinking: str | None = Field(None, max_length=64)
    reasoning_effort: str | None = Field(None, max_length=64)
