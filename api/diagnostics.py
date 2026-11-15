from fastapi import APIRouter, Depends, Response

from auth.deps import AuthContext, get_auth_context
from services.diagnostics import recent_tasks
from utils.response_format import ResponseSchema

router = APIRouter()


@router.get('/recent', response_model=ResponseSchema)
async def recent(response: Response, ctx: AuthContext = Depends(get_auth_context)):
    response.headers['Cache-Control'] = 'no-store'
    return ResponseSchema(data=await recent_tasks(ctx))
