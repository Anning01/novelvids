"""Resolve private methods and freeze only the selected skill for a task."""

import hashlib
import json
from datetime import datetime, timezone
from fastapi import HTTPException
from tortoise.expressions import F
from models.user_skill import UserSkill, TaskSkillPreference
from prompts.text_tasks import builtin_method
from utils.messages import localized_message
from utils.skill_package import PACKAGE_LIMITS, SkillPackage
from prompts.skill_packages import legacy_package


def owner_id(ctx):
    return ctx.user.id if ctx.user else 0


def skill_data(row, *, include_files=True):
    result = {key: getattr(row, key) for key in (
        'id', 'task', 'name', 'description', 'version', 'is_active')} | {'builtin': False}
    if include_files:
        result.update(instructions=row.instructions, references=row.references)
        result['files'] = (row.files or legacy_package(row.task, row.instructions, row.references, row.description).files)
        result['limits'] = PACKAGE_LIMITS
    else:
        result.update(instructions='', references=[], is_summary=True)
    return result


def summary_data(data):
    return {key: value for key, value in data.items() if key not in ('files', 'limits', 'file_manifest', 'instructions', 'references')} | {
        'instructions': '', 'references': [], 'is_summary': True}


def package_from_input(body) -> SkillPackage:
    try:
        package = SkillPackage([file.model_dump() for file in body.files]) if body.files is not None else legacy_package(
            body.task, body.instructions, [item.model_dump() for item in body.references], body.description)
        return package
    except ValueError as error:
        raise HTTPException(400, localized_message(str(error))) from None


async def get_skill(identifier, owner, task=None, *, summary=False):
    query = UserSkill.filter(id=identifier, owner_id=owner)
    if summary:
        query = query.only('id', 'task', 'name', 'description', 'version', 'is_active')
    row = await query.first()
    if row is None or (task is not None and row.task != task):
        raise HTTPException(404, localized_message('技能不存在或不适用于当前任务'))
    return row


async def list_skills(owner, task):
    rows = await UserSkill.filter(owner_id=owner, task=task).only(
        'id', 'task', 'name', 'description', 'version', 'is_active').order_by('-updated_at', '-id')
    preference = await TaskSkillPreference.get_or_none(owner_id=owner, task=task)
    builtin = builtin_method(task, include_files=False)
    return {'items': [builtin, *(skill_data(row, include_files=False) for row in rows)],
            'default_skill_id': preference.skill_id if preference else 0}


async def save_skill(owner, body, identifier=None):
    values = body.model_dump(exclude={'expected_version', 'files'}, exclude_none=True)
    if body.files is not None:
        package = package_from_input(body)
        values.update(files=package.files, instructions=package.body,
            name=body.name or package.metadata['name'], description=body.description or package.metadata['description'][:1000])
        # Old reference records remain available for compatibility, never silently deleted.
        values.pop('references', None)
    if identifier is None:
        return skill_data(await UserSkill.create(owner_id=owner, **values))
    row = await get_skill(identifier, owner, body.task, summary=body.files is not None)
    if body.files is None and row.files:
        raise HTTPException(409, localized_message('此技能已使用文件夹格式，请刷新后编辑'))
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
        row = await get_skill(identifier, owner, task, summary=True)
        if not row.is_active:
            raise HTTPException(409, localized_message('技能已停用'))
    await TaskSkillPreference.update_or_create(owner_id=owner, task=task, defaults={'skill_id': identifier})


async def set_active(owner, identifier, body):
    row = await get_skill(identifier, owner, summary=True)
    changed = await UserSkill.filter(id=row.id, owner_id=owner, version=body.expected_version).update(
        is_active=body.is_active, version=F('version') + 1, updated_at=datetime.now(timezone.utc))
    if not changed:
        raise HTTPException(409, localized_message('技能已被修改，请重新读取后保存'))
    if not body.is_active:
        await TaskSkillPreference.filter(owner_id=owner, skill_id=row.id).update(skill_id=0)
    row.is_active = body.is_active
    row.version = body.expected_version + 1
    return skill_data(row, include_files=False)


async def snapshot_method(owner, task, identifier=None, *, blocking_maps=False):
    if identifier is None:
        preference = await TaskSkillPreference.get_or_none(owner_id=owner, task=task)
        identifier = preference.skill_id if preference else 0
    if identifier:
        row = await get_skill(identifier, owner, task)
        if not row.is_active:
            raise HTTPException(409, localized_message('技能已停用'))
        result = skill_data(row)
        if row.files:
            try:
                result.update(SkillPackage(row.files).as_method())
            except ValueError as error:
                raise HTTPException(400, localized_message(str(error))) from None
    else:
        result = builtin_method(task, blocking_maps=blocking_maps)
    result = {key: value for key, value in result.items() if key not in ('limits', 'is_summary')}
    revision = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {key: value for key, value in result.items() if key != 'files'} | {'revision': revision}


async def detail_skill(owner, task, identifier):
    return builtin_method(task) if identifier == 0 else skill_data(await get_skill(identifier, owner, task))
