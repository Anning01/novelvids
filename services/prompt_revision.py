"""Atomic preconditions shared by manual Prompt editors and Agent updates."""

from fastapi import HTTPException
from tortoise import timezone


async def apply_prompt_precondition(instance, data: dict, field: str) -> bool:
    if "expected_prompt" not in data:
        return False
    expected = data.pop("expected_prompt")
    if field not in data:
        raise HTTPException(422, "提示词版本检查必须与提示词修改一起提交")
    updated = await type(instance).filter(id=instance.id, **{field: expected}).update(
        **data, updated_at=timezone.now())
    if not updated:
        raise HTTPException(409, "提示词已被其他操作修改，本地草稿未覆盖新内容，请重新读取后核对")
    await instance.refresh_from_db()
    return True
