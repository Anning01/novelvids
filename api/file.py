from fastapi import APIRouter, Depends, File, Query, UploadFile
from datetime import datetime
import asyncio
import os
import shutil
from pathlib import Path

from pydantic import BaseModel, Field

from auth.deps import AuthContext, require_roles
from services.document import analyze_document, analyze_oss_document
from services.oss import make_upload_key, oss
from utils.response_format import ResponseSchema
from config import settings

router = APIRouter()

_EDITOR = Depends(require_roles("admin", "creator"))

# 浏览器直传 OSS 的文件大小上限（字节）。需覆盖所有上传入口的前端校验上限：
# 图片标注 30MB、参考图片 30MB、首尾帧 20MB、参考视频 200MB（capabilities）。
# 上限过低（曾为 20MB）会导致超过的文件直传返回 400 EntityTooLarge。
_DIRECT_UPLOAD_MAX_BYTES = 200 * 1024 * 1024


class OssFinalizeIn(BaseModel):
    key: str = Field(min_length=1, max_length=500, description="OSS 对象 key")
    original_filename: str = Field(min_length=1, max_length=255, description="原始文件名")


@router.get("/upload-policy", summary="获取直传 OSS 的策略（未启用时 direct=false）")
async def get_upload_policy(
    filename: str = Query(..., max_length=255),
    content_type: str = Query("application/octet-stream", max_length=120),
    _: AuthContext = _EDITOR,
):
    if not oss.enabled:
        return ResponseSchema(data={"direct": False})
    key = make_upload_key(None, filename)
    policy = oss.sign_form_upload(key, content_type, _DIRECT_UPLOAD_MAX_BYTES)
    return ResponseSchema(
        data={
            "direct": True,
            "provider": oss.name,
            "key": key,
            "upload_url": policy["url"],
            "fields": policy["fields"],
            "public_url": oss.public_url(key),
            "filename": Path(filename).name,
        }
    )


@router.post("/oss-finalize", summary="OSS 直传后终局：服务端经内网读取并做书稿分析")
async def oss_finalize(
    payload: OssFinalizeIn,
    _: AuthContext = _EDITOR,
):
    if not oss.enabled:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="未启用对象存储")
    analysis = await analyze_oss_document(payload.key, payload.original_filename)
    return ResponseSchema(
        data={
            "filename": Path(payload.original_filename).name,
            "url": oss.public_url(payload.key),
            "key": payload.key,
            "text_content": analysis["text_content"],
            "chapter_validation": analysis["chapter_validation"],
            "message": "文件上传成功",
        }
    )


@router.post("/upload", summary="多文件上传", response_model=ResponseSchema[dict])
async def upload_files(
    files: list[UploadFile] = File(...),
    _: AuthContext = _EDITOR,
):
    """处理多文件上传"""
    try:
        results = []

        # 循环处理每个文件
        for file in files:
            # 生成唯一的文件名，避免覆盖
            timestamp = datetime.now(settings.tz).strftime("%Y%m%d%H%M%S")
            # 为每个文件添加唯一标识，避免同一时间上传的文件重名
            unique_id = f"{timestamp}_{os.urandom(4).hex()}"

            # 截断原始文件名到最长10个字符，但保留扩展名
            original_filename = file.filename
            # 分离文件名和扩展名
            name_part, ext_part = os.path.splitext(original_filename)
            # 只截取文件名部分的前10个字符，保留扩展名
            truncated_name = name_part[:10]
            # 构建新文件名（保留原始扩展名）
            filename = f"{unique_id}_{truncated_name}{ext_part}"
            file_path = os.path.join(settings.MEDIA_PATH, filename)

            # 保存文件
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

            analysis = await asyncio.to_thread(
                analyze_document,
                file_path,
                original_filename,
            )
            text_content = analysis["text_content"]
            chapter_validation = analysis["chapter_validation"]

            # 记录结果
            results.append(
                {
                    "filename": filename,
                    "original_filename": original_filename,
                    "content_type": file.content_type,
                    "file_path": file_path,
                    "text_content": text_content,
                    "chapter_validation": chapter_validation,
                    "message": "文件上传成功",
                }
            )

        return ResponseSchema(data={"total": len(results), "files": results})
    except Exception as e:
        return ResponseSchema(code=500, data={"error": str(e)}, message="上传失败")
