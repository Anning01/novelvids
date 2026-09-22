"""Complete creative inputs for CRUD tests, using the production field contracts."""

from prompts.storyboard import format_storyboard_prompt
from test.test_services.test_extraction_prompt_preparation import PERSON_TRAITS
from test.test_services.test_storyboard_prompts import _shot


def person_traits(**fields: str) -> str:
    values = dict(line.split(': ', 1) for line in PERSON_TRAITS.splitlines())
    values.update(fields)
    return '\n'.join(f'{name}: {value}' for name, value in values.items())


def full_scene_prompt(text: str, duration: int = 3) -> str:
    shot = _shot(1).model_copy(update={'duration': f'{duration}s', 'description': text,
        'visual_prose': text, 'actions': [f'0s-{duration}s: {text}']})
    return format_storyboard_prompt(shot)
