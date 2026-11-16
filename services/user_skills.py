"""Resolve private methods and freeze only the selected skill for a task."""

import hashlib
import json
from datetime import datetime, timezone
from fastapi import HTTPException
from tortoise.expressions import F
from models.user_skill import UserSkill, TaskSkillPreference
from prompts.text_tasks import builtin_method
from utils.messages import localized_message


def owner_id(ctx):
    return ctx.user.id if ctx.user else 0


def skill_data(row):
    return {key: getattr(row, key) for key in (
        'id', 'task', 'name', 'description', 'instructions', 'references', 'version', 'is_active')} | {'builtin': False}


async def get_skill(identifier, owner, task=None):
    row = await UserSkill.get_or_none(id=identifier, owner_id=owner)
    if row is None or (task is not None and row.task != task):
        raise HTTPException(404, localized_message('技能不存在或不适用于当前任务'))
    return row


async def list_skills(owner, task):
    rows = await UserSkill.filter(owner_id=owner, task=task).order_by('-updated_at', '-id')
    preference = await TaskSkillPreference.get_or_none(owner_id=owner, task=task)
    return {'items': [builtin_method(task), *(skill_data(row) for row in rows)],
            'default_skill_id': preference.skill_id if preference else 0}


async def save_skill(owner, body, identifier=None):
    values = body.model_dump(exclude={'expected_version'})
    if identifier is None:
        return skill_data(await UserSkill.create(owner_id=owner, **values))
    row = await get_skill(identifier, owner, body.task)
    changed = await UserSkill.filter(id=row.id, owner_id=owner, version=body.expected_version).update(
        **values, version=F('version') + 1, updated_at=datetime.now(timezone.utc))
    if not changed:
        raise HTTPException(409, localized_message('技能已被修改，请重新读取后保存'))
    if not body.is_active:
        await TaskSkillPreference.filter(owner_id=owner, skill_id=row.id).update(skill_id=0)
    await row.refresh_from_db()
    return skill_data(row)


async def set_default(owner, task, identifier):
    if identifier:
        row = await get_skill(identifier, owner, task)
        if not row.is_active:
            raise HTTPException(409, localized_message('技能已停用'))
    await TaskSkillPreference.update_or_create(owner_id=owner, task=task, defaults={'skill_id': identifier})


async def snapshot_method(owner, task, identifier=None):
    if identifier is None:
        preference = await TaskSkillPreference.get_or_none(owner_id=owner, task=task)
        identifier = preference.skill_id if preference else 0
    if identifier:
        row = await get_skill(identifier, owner, task)
        if not row.is_active:
            raise HTTPException(409, localized_message('技能已停用'))
        result = skill_data(row)
    else:
        result = builtin_method(task)
    revision = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {**result, 'revision': revision}
