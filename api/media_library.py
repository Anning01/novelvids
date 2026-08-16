from fastapi import APIRouter, Depends

from auth.deps import AuthContext, get_auth_context
from controllers.media_library import (
    AUDIO_SEARCH_FIELDS,
    DIGITAL_HUMAN_SEARCH_FIELDS,
    audio_reference_controller,
    digital_human_controller,
)
from models.audio_reference import AudioReference
from models.digital_human import DigitalHuman
from schemas.media_library import AudioReferenceOut, DigitalHumanOut
from utils.page import QueryParams, get_list_params
from utils.response_format import PaginationResponse, ResponseSchema

router = APIRouter()


@router.get(
    "/audio-references",
    summary="获取启用的参考音频",
    response_model=ResponseSchema[PaginationResponse[AudioReferenceOut]],
)
async def list_audio_references(
    params: QueryParams = Depends(get_list_params),
    _: AuthContext = Depends(get_auth_context),
):
    data = await audio_reference_controller.list(
        params,
        AudioReferenceOut,
        AUDIO_SEARCH_FIELDS,
        AudioReference.filter(is_active=True),
    )
    return ResponseSchema(data=data)


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
