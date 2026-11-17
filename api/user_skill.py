from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from auth.deps import AuthContext, require_roles
from schemas.user_skill import TextTask, UserSkillInput, UserSkillUpdate, SkillPreferenceInput, SkillTrialInput
from services import user_skills
from services.model_resolution import resolve_scope_configs
from utils.enums import AiTaskTypeEnum
from utils.response_format import ResponseSchema

router = APIRouter()
_EDITOR = Depends(require_roles('admin', 'creator'))


@router.get('/models', response_model=ResponseSchema)
async def models(ctx: AuthContext = _EDITOR):
    configs = await resolve_scope_configs(AiTaskTypeEnum.creation_agent.value, ctx.team_id,
        capability_filter=lambda config: config.supports_json_output)
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
    return ResponseSchema(data=await user_skills.save_skill(user_skills.owner_id(ctx), body))


@router.put('/default/{task}', response_model=ResponseSchema)
async def default_skill(task: TextTask, body: SkillPreferenceInput, ctx: AuthContext = _EDITOR):
    await user_skills.set_default(user_skills.owner_id(ctx), task, body.skill_id)
    return ResponseSchema()


@router.put('/{skill_id}', response_model=ResponseSchema)
async def update_skill(skill_id: int, body: UserSkillUpdate, ctx: AuthContext = _EDITOR):
    return ResponseSchema(data=await user_skills.save_skill(user_skills.owner_id(ctx), body, skill_id))
