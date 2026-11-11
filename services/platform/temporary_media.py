"""Issue upload permissions and expire previously issued studio objects without receiving content."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import re

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field
from tortoise.expressions import F, Q
from tortoise.functions import Sum
from tortoise.transactions import in_transaction

from auth.models import StudioMediaLease, Team
from config import settings
from services.oss.temporary import TemporaryBucket, suppress_signed_queries

PREFIX = "studio-temporary/v1/"
READ_SECONDS = 48 * 60 * 60
UPLOAD_SECONDS = 10 * 60
TYPES = {"image/png":"png","image/jpeg":"jpg","image/webp":"webp","image/gif":"gif","image/bmp":"bmp",
         "image/heic":"heic","image/heif":"heif","image/tiff":"tif","video/mp4":"mp4","video/quicktime":"mov",
         "audio/wav":"wav","audio/x-wav":"wav","audio/mpeg":"mp3","audio/mp4":"m4a","audio/flac":"flac",
         "audio/ogg":"ogg","audio/aac":"aac"}


class UploadSpec(BaseModel):
    content_type: str = Field(max_length=64)
    byte_length: int = Field(gt=0, le=5 * 1024**3)
    content_md5: str = Field(pattern=r"^[A-Za-z0-9+/]{22}==$")


def bucket_config():
    if not (re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", settings.STUDIO_TEMP_BUCKET)
            and re.fullmatch(r"[a-z0-9-]+", settings.STUDIO_TEMP_REGION)
            and settings.OSS_ACCESS_KEY_ID and settings.OSS_ACCESS_KEY_SECRET):
        return None
    return TemporaryBucket(settings.STUDIO_TEMP_BUCKET, settings.STUDIO_TEMP_REGION,
                           settings.OSS_ACCESS_KEY_ID, settings.OSS_ACCESS_KEY_SECRET)


async def issue_upload(team_id, spec):
    bucket = bucket_config()
    if not bucket:
        raise HTTPException(503, "平台临时素材存储尚未配置")
    if spec.content_type not in TYPES:
        raise HTTPException(422, "不支持的参考素材类型")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    expires = now + timedelta(seconds=READ_SECONDS)
    key = f"{PREFIX}{team_id}/{uuid4().hex}.{TYPES[spec.content_type]}"
    async with in_transaction() as db:
        if not await Team.filter(id=team_id, status=1).using_db(db).update(status=F("status")):
            raise HTTPException(403, "团队已停用")
        totals = await StudioMediaLease.filter(team_id=team_id).using_db(db).annotate(total=Sum("byte_length")).values_list("total",flat=True)
        allocated = sum(t or 0 for t in totals)
        if allocated + spec.byte_length > settings.STUDIO_TEMP_TEAM_BYTES:
            raise HTTPException(429, "团队临时素材空间已满")
        await StudioMediaLease.create(using_db=db, object_key=key, bucket=bucket.bucket, region=bucket.region,
                                      team_id=team_id, byte_length=spec.byte_length, expires_epoch=int(expires.timestamp()))
    headers = {"content-length":str(spec.byte_length), "content-type":spec.content_type, "content-md5":spec.content_md5,
               "x-oss-object-acl":"private","x-oss-forbid-overwrite":"true"}
    return {"upload_url":bucket.sign("PUT",key,now,UPLOAD_SECONDS,headers),"headers":headers,
            "read_url":bucket.sign("GET",key,now,READ_SECONDS),"expires_at":int(expires.timestamp())}


async def expire_uploads():
    bucket = bucket_config()
    if bucket is None:
        return
    now = datetime.now(timezone.utc)
    epoch = int(now.timestamp())
    due = await StudioMediaLease.filter(Q(retry_epoch__isnull=True) | Q(retry_epoch__lte=epoch), bucket=bucket.bucket,
                                        region=bucket.region, expires_epoch__lte=epoch).order_by("expires_epoch").limit(100)
    if not due:
        return
    suppress_signed_queries()
    async with httpx.AsyncClient(timeout=15) as client:
        for record in due:
            if not record.object_key.startswith(f"{PREFIX}{record.team_id}/"):
                continue
            url = bucket.sign("DELETE",record.object_key,datetime.now(timezone.utc),60)
            try:
                status = (await client.delete(url)).status_code
            except httpx.HTTPError:
                status = None
            if status in (200, 204, 404):
                await StudioMediaLease.filter(id=record.id).delete()
            else:
                await StudioMediaLease.filter(id=record.id).update(retry_epoch=epoch+300)

async def expire_periodically():
    while True:
        try:
            await expire_uploads()
        except Exception:
            logging.getLogger(__name__).error("Temporary object cleanup deferred")
        await asyncio.sleep(60)
