from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException
from fastapi.responses import StreamingResponse, Response
from starlette.concurrency import run_in_threadpool
from auth.deps import AuthContext, require_roles
from schemas.user_skill import TextTask, UserSkillInput, UserSkillUpdate, SkillPreferenceInput, SkillTrialInput, SkillStatusInput
from services import user_skills
from services.model_resolution import resolve_scope_configs
from utils.enums import AiTaskTypeEnum
from utils.response_format import ResponseSchema

router = APIRouter()
_EDITOR = Depends(require_roles('admin', 'creator'))


@router.get('/package-format', response_model=ResponseSchema)
async def package_format(task: TextTask, ctx: AuthContext = _EDITOR):
    from utils.skill_package import PACKAGE_LIMITS
    from prompts.skill_packages import legacy_package
    return ResponseSchema(data={'files': legacy_package(task, '', []).files, 'limits': PACKAGE_LIMITS})


@router.post('/import', response_model=ResponseSchema)
async def import_skill(task: TextTask = Form(...), file: UploadFile = File(...), ctx: AuthContext = _EDITOR):
    from utils.skill_package import MAX_ARCHIVE_BYTES, PACKAGE_LIMITS, SkillPackage
    from utils.messages import localized_message
    chunks, total = [], 0
    try:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_ARCHIVE_BYTES:
                raise ValueError('压缩包最多 20 MB')
            chunks.append(chunk)
        package = await run_in_threadpool(SkillPackage.from_archive, b''.join(chunks))
    except ValueError as error:
        raise HTTPException(400, localized_message(str(error))) from None
    finally:
        await file.close()
    return ResponseSchema(data={'task': task, 'name': package.metadata['name'],
        'description': package.metadata['description'][:1000], 'files': package.files,
        'instructions': package.body, 'references': [], 'is_active': True, 'limits': PACKAGE_LIMITS})


@router.post('/export')
async def export_skill(body: UserSkillInput, ctx: AuthContext = _EDITOR):
    package = user_skills.package_from_input(body)
    content = await run_in_threadpool(package.archive)
    return Response(content, media_type='application/zip',
        headers={'Content-Disposition': f'attachment; filename="{package.metadata["name"]}.zip"'})


@router.get('/models', response_model=ResponseSchema)
async def models(ctx: AuthContext = _EDITOR):
    configs = await resolve_scope_configs(AiTaskTypeEnum.creation_agent.value, ctx.team_id,
        capability_filter=lambda config: config.supports_strict_output)
    return ResponseSchema(data=[{'id': row.id, 'name': row.name, 'model': row.model} for row in configs])


@router.post('/trial')
async def trial_skill(body: SkillTrialInput, ctx: AuthContext = _EDITOR):
    from services.skill_trial import prepare_trial, stream_trial
    prepared = await prepare_trial(body, ctx)
    return StreamingResponse(stream_trial(body, ctx, prepared), media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@router.get('', response_model=ResponseSchema)
async def list_skills(task: TextTask, ctx: AuthContext = _EDITOR):
    return ResponseSchema(data=await user_skills.list_skills(user_skills.owner_id(ctx), task))


@router.post('', response_model=ResponseSchema)
async def create_skill(body: UserSkillInput, ctx: AuthContext = _EDITOR):
    data = await user_skills.save_skill(user_skills.owner_id(ctx), body)
    return ResponseSchema(data=user_skills.summary_data(data) if body.files is not None else data)


@router.get('/{skill_id}', response_model=ResponseSchema)
async def detail_skill(skill_id: int, task: TextTask, ctx: AuthContext = _EDITOR):
    return ResponseSchema(data=await user_skills.detail_skill(user_skills.owner_id(ctx), task, skill_id))


@router.put('/default/{task}', response_model=ResponseSchema)
async def default_skill(task: TextTask, body: SkillPreferenceInput, ctx: AuthContext = _EDITOR):
    await user_skills.set_default(user_skills.owner_id(ctx), task, body.skill_id)
    return ResponseSchema()


@router.patch('/{skill_id}/status', response_model=ResponseSchema)
async def skill_status(skill_id: int, body: SkillStatusInput, ctx: AuthContext = _EDITOR):
    return ResponseSchema(data=await user_skills.set_active(user_skills.owner_id(ctx), skill_id, body))


@router.put('/{skill_id}', response_model=ResponseSchema)
async def update_skill(skill_id: int, body: UserSkillUpdate, ctx: AuthContext = _EDITOR):
    data = await user_skills.save_skill(user_skills.owner_id(ctx), body, skill_id)
    return ResponseSchema(data=user_skills.summary_data(data) if body.files is not None else data)
