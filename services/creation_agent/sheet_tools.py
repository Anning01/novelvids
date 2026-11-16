"""Thin Agent adapters for existing sheet tasks and history."""
from uuid import UUID, uuid5

from services.creation_agent.operation_receipts import execute_step
from services.creation_agent.skill_execution import current_execution
from services.creation_agent.submissions import submission
from services.video_enhancement.media import digest
from schemas.storyboard_sheet import SheetEditRequest
from utils.messages import localized_message as msg


async def scene_for(service, scene_id, *, write=False):
    await service.authorize()
    scene = await service.objects.get('scene', scene_id)
    if write:
        await service.scope.target('scene', scene)
    return scene


async def edit_sheet(service, scene_id, expected_revision, model_config_id=None):
    await scene_for(service, scene_id, write=True)
    execution = current_execution.get()
    if execution is None:
        raise ValueError(msg('此历史运行不支持生成'))
    # Only the user's frozen message supplies editing instructions, never the model's paraphrase.
    payload = SheetEditRequest(instruction=service.request.message, expected_revision=expected_revision, model_config_id=model_config_id)
    key = 'submit:sheet-edit:' + digest([scene_id, payload.model_dump()])

    async def submit():
        from services.storyboard.sheets import submit_sheet_edit
        params = execution.params
        token = submission.set({'submission_id': str(uuid5(UUID(str(service.task_id)), key)), 'submission_hash': digest(key)})
        try:
            task = await submit_sheet_edit(scene_id, payload, team_id=params.get('team_id'), user_id=params.get('user_id'))
        finally:
            submission.reset(token)
        return {'task_id': str(task.id), 'scene_id': scene_id, 'operation': 'storyboard_sheet_edit', 'status': 'submitted'}

    return await execute_step(service.task_id, key, submit, atomic=True)
