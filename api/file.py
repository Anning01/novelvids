from fastapi import APIRouter, File, UploadFile
from datetime import datetime
import os
import shutil
from utils.response_format import ResponseSchema
from config import settings

router = APIRouter()

@router.post("/upload", summary="多文件上传", response_model=ResponseSchema[dict])
async def upload_files(
    files: list[UploadFile] = File(...)
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

            # 记录结果
            results.append(
                {
                    "filename": filename,
                    "original_filename": original_filename,
                    "content_type": file.content_type,
                    "file_path": file_path,
                    "message": "文件上传成功",
                }
            )

        return ResponseSchema(data={"total": len(results), "files": results})
    except Exception as e:
        return ResponseSchema(code=500, data={"error": str(e)}, message="上传失败")
