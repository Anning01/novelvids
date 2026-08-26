from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from auth.deps import AuthContext, ensure_novel_access, get_auth_context, require_roles
from controllers.media_library import (
    AUDIO_SEARCH_FIELDS,
    DIGITAL_HUMAN_SEARCH_FIELDS,
    audio_reference_controller,
    digital_human_controller,
)
from models.audio_reference import AudioReference
from models.digital_human import DigitalHuman
from models.novel import Novel
from schemas.media_library import AudioReferenceOssFinalizeIn, AudioReferenceOut, AudioReferenceTrimIn, DigitalHumanOut
from services.audio_references import (
    audio_reference_accessible,
    audio_reference_scope_query,
    finalize_oss_audio_reference,
    save_uploaded_audio_reference,
    trim_audio_reference,
)
from utils.page import QueryParams, get_list_params
from utils.response_format import PaginationResponse, ResponseSchema

router = APIRouter()
_EDITOR = Depends(require_roles("admin", "creator"))


async def _audio_project_scope(
    novel_id: int | None,
    ctx: AuthContext,
) -> tuple[int | None, int | None]:
    """返回音色上传/列表使用的项目团队和创建人作用域。"""
    if novel_id is None:
        return ctx.team_id, ctx.user.id if ctx.user else None
    await ensure_novel_access(novel_id, ctx)
    novel = await Novel.get_or_none(id=novel_id)
    if novel is None:
        from fastapi import HTTPException

        raise HTTPException(404, detail="项目不存在")
    return novel.team_id, novel.created_by


@router.get(
    "/audio-references",
    summary="获取启用的参考音频",
    response_model=ResponseSchema[PaginationResponse[AudioReferenceOut]],
)
async def list_audio_references(
    params: QueryParams = Depends(get_list_params),
    ctx: AuthContext = Depends(get_auth_context),
    novel_id: int | None = Query(default=None, ge=1),
):
    query = AudioReference.filter(is_active=True)
    if novel_id is not None:
        team_id, created_by = await _audio_project_scope(novel_id, ctx)
        query = query.filter(audio_reference_scope_query(
            team_id=team_id,
            created_by=created_by,
        ))
    elif ctx.user is not None and not ctx.is_super_admin:
        query = query.filter(audio_reference_scope_query(
            team_id=ctx.team_id,
            created_by=ctx.user.id,
        ))
    data = await audio_reference_controller.list(
        params,
        AudioReferenceOut,
        AUDIO_SEARCH_FIELDS,
        query,
    )
    return ResponseSchema(data=data)


@router.post(
    "/audio-references/upload",
    summary="上传可复用参考音频",
    response_model=ResponseSchema[AudioReferenceOut],
)
async def upload_audio_reference(
    nickname: str = Form(..., min_length=1, max_length=100),
    gender: str = Form("未设置", max_length=32),
    novel_id: int | None = Form(default=None),
    file: UploadFile = File(...),
    ctx: AuthContext = Depends(get_auth_context),
    _: AuthContext = _EDITOR,
):
    team_id, _ = await _audio_project_scope(novel_id, ctx)
    reference = await save_uploaded_audio_reference(
        file,
        nickname=nickname,
        gender=gender,
        team_id=team_id,
        created_by=ctx.user.id if ctx.user else None,
    )
    return ResponseSchema(data=AudioReferenceOut.model_validate(reference))


@router.post(
    "/audio-references/oss-finalize",
    summary="OSS 直传后经内网校验并登记参考音频",
    response_model=ResponseSchema[AudioReferenceOut],
)
async def finalize_audio_reference_oss(
    payload: AudioReferenceOssFinalizeIn,
    ctx: AuthContext = Depends(get_auth_context),
    _: AuthContext = _EDITOR,
):
    team_id, _ = await _audio_project_scope(payload.novel_id, ctx)
    reference = await finalize_oss_audio_reference(
        key=payload.key,
        filename=payload.filename,
        nickname=payload.nickname,
        gender=payload.gender,
        team_id=team_id,
        created_by=ctx.user.id if ctx.user else None,
    )
    return ResponseSchema(data=AudioReferenceOut.model_validate(reference))


@router.post(
    "/audio-references/{reference_id}/trim",
    summary="裁剪用户上传的参考音频",
    response_model=ResponseSchema[AudioReferenceOut],
)
async def trim_uploaded_audio_reference(
    reference_id: int,
    payload: AudioReferenceTrimIn,
    ctx: AuthContext = Depends(get_auth_context),
    _: AuthContext = _EDITOR,
):
    team_id, created_by = await _audio_project_scope(payload.novel_id, ctx)
    reference = await AudioReference.get_or_none(id=reference_id, is_active=True)
    if reference is None or not audio_reference_accessible(
        reference,
        team_id=team_id,
        created_by=created_by,
    ):
        from fastapi import HTTPException

        raise HTTPException(404, detail="音色不存在")
    clipped = await trim_audio_reference(
        reference,
        start=payload.start,
        end=payload.end,
        team_id=team_id,
        created_by=ctx.user.id if ctx.user else None,
    )
    return ResponseSchema(data=AudioReferenceOut.model_validate(clipped))


@router.get(
    "/digital-humans",
    summary="获取启用的纯数字人",
    response_model=ResponseSchema[PaginationResponse[DigitalHumanOut]],
)
async def list_digital_humans(
    params: QueryParams = Depends(get_list_params),
    _: AuthContext = Depends(get_auth_context),
):
    data = await digital_human_controller.list(
        params,
        DigitalHumanOut,
        DIGITAL_HUMAN_SEARCH_FIELDS,
        DigitalHuman.filter(is_active=True),
    )
    return ResponseSchema(data=data)
