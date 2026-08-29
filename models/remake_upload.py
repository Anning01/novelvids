from datetime import datetime, timedelta, timezone

from tortoise import fields

from models._base import AbstractBaseModel


def _upload_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=24)


class RemakeUpload(AbstractBaseModel):
    """创建重制项目之前的一次性来源媒体暂存记录。"""

    id = fields.UUIDField(primary_key=True, description="不透明上传 token")
    storage_provider = fields.CharField(max_length=16, description="local/oss")
    object_key = fields.CharField(max_length=500, unique=True, description="受控媒体 key")
    original_filename = fields.CharField(max_length=255, description="原始文件名")
    mime_type = fields.CharField(max_length=120, null=True, description="展示用 MIME")
    size_bytes = fields.BigIntField(default=0, description="媒体字节数")
    duration_seconds = fields.FloatField(null=True, description="媒体时长")
    width = fields.IntField(null=True, description="视频宽度")
    height = fields.IntField(null=True, description="视频高度")
    container_format = fields.CharField(max_length=32, null=True, description="真实容器")
    checksum = fields.CharField(max_length=64, null=True, description="SHA-256")
    status = fields.CharField(
        max_length=16,
        default="uploading",
        db_index=True,
        description="uploading/validating/ready/committed/failed/expired",
    )
    error_code = fields.CharField(max_length=64, null=True, description="稳定错误码")
    error_message = fields.TextField(null=True, description="用户可理解错误")
    team_id = fields.IntField(null=True, db_index=True, description="所属团队")
    created_by = fields.IntField(null=True, db_index=True, description="创建人")
    expires_at = fields.DatetimeField(default=_upload_expiry, db_index=True, description="过期时间")
    committed_at = fields.DatetimeField(null=True, description="项目绑定时间")

    class Meta:
        table = "remake_uploads"
        table_description = "重制来源视频暂存"
