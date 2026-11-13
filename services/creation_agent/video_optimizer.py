"""Freeze only the selected, installed official prompt skill; never execute its files."""

import json
from pathlib import Path

from config import settings
from models.novel import Novel
from prompts.skill_pack import read_skill


def snapshot_optimizer(model_type: str | None, root: Path) -> dict:
    registry = json.loads(read_skill('video_prompt_models'))
    profile = next((item for key, item in registry.items()
                    if (model_type or '').casefold() in {key.casefold(), *(alias.casefold() for alias in item['aliases'])}), None)
    if profile is None:
        return {'mode': 'generic', 'model_type': model_type}
    name = profile['skill']
    package = (root / name).resolve()
    entry = package / 'SKILL.md'
    if not entry.is_file():
        return {'mode': 'missing', 'model_type': model_type, 'skill': name}
    files = {}
    for path in sorted(package.rglob('*')):
        if path.is_file() and path.suffix in {'.md', '.txt', '.json'} and path.resolve().is_relative_to(package):
            files[str(path.relative_to(package))] = path.read_text(encoding='utf-8')
    return {'mode': 'optimize', 'model_type': model_type, 'skill': name, 'files': files}


async def project_optimizer(novel_id: int, team_id: int | None = None) -> dict:
    novel = await Novel.get(id=novel_id)
    if not novel.video_model_config_id:
        return {'mode': 'generic', 'model_type': None}
    from controllers.config import ai_model_config_controller
    config = await ai_model_config_controller.get_active(4, novel.video_model_config_id, team_id=team_id)
    return snapshot_optimizer(config.video_model_type, Path(settings.CREATION_AGENT_OPTIONAL_SKILLS_PATH))


def optimizer_instructions(optimizer: dict) -> str:
    if optimizer.get('mode') != 'optimize':
        return ''
    from prompts.video_optimizer import render_optimizer_instructions
    return render_optimizer_instructions(optimizer['skill'], optimizer['files'])
