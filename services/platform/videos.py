"""Remote video jobs are durable control-plane records. Video bytes are fetched by the caller."""
import asyncio
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
import logging
import re
from math import isfinite
import time
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from tortoise.transactions import in_transaction
from auth.models import PlatformCallReceipt, PlatformVideoJob
from models.config import AiModelConfig
from services.billing.pricing import compute_input_image_cost, compute_video_cost
from services.platform.calls import CALL_TIMEOUT, admit, digest, settle
from services.platform.images import media_url
from services.video import get_generator
from services.video.base import VideoProviderError
from services.video.capabilities import capabilities_for, validate_selection
from utils.enums import TaskStatusEnum

logger = logging.getLogger(__name__)


class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["image", "video", "audio"]
    role: Literal["reference", "first_frame", "last_frame"] = "reference"
    url: str
    _url = field_validator("url")(media_url)


class VideoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(pattern=r"^nv-[1-9][0-9]{0,9}$")
    prompt: str = Field(min_length=1)
    duration: int = Field(gt=0)
    resolution: str
    aspect_ratio: str
    references: list[Reference] = Field(default_factory=list)
    generate_audio: bool | None = None
    return_last_frame: bool = False
    watermark: Literal[False] = False
    request_id: UUID | None = None

    @model_validator(mode="after")
    def reference_roles(self):
        roles = [r.role for r in self.references]
        if any(r != "reference" for r in roles):
            if sorted(roles) != ["first_frame","last_frame"] or any(r.type != "image" for r in self.references):
                raise ValueError("首尾帧须分别提供一张图片")
        elif len({(r.type,r.url) for r in self.references}) != len(roles):
            raise ValueError("参考素材重复")
        return self


def video_options(config, body):
    if 4 not in (config.task_types or [config.task_type]) or config.api_protocol == "novelvids":
        raise HTTPException(422, "所选配置不是上游视频模型")
    refs = body["references"]
    mode = "keyframes" if any(r["role"]=="first_frame" for r in refs) else "reference"
    selected = validate_selection(config.video_model_type, api_protocol=config.api_protocol, generation_mode=mode,
        resolution=body["resolution"],aspect_ratio=body["aspect_ratio"],duration=body["duration"],output_format="mp4",
        generate_audio=body.get("generate_audio"),return_last_frame=body["return_last_frame"])
    caps = capabilities_for(config.video_model_type,config.api_protocol)
    counts = Counter(r["type"] for r in refs)
    if mode=="reference" and (counts["image"] > caps.max_reference_images or counts["video"] > caps.max_reference_videos
                              or counts["audio"] > caps.max_reference_audios):
        raise HTTPException(422, "参考素材数量超过所选模型限制")
    rates = config.pricing or {}
    prices = rates.get("prices") or {}
    tariffs = [prices.get(selected.resolution)]
    if counts["video"]:
        tariffs.append((rates.get("video_reference_prices") or prices).get(selected.resolution))
    if rates.get("type")!="video" or not all(type(v) in {float,int} and isfinite(v) and v>=0 for v in tariffs):
        raise HTTPException(422, "所选分辨率尚未配置视频价格")
    return rates


def route_hash(config):
    return digest([config.base_url,config.api_protocol,config.model,config.video_model_type])


async def submit_video(ctx, request, key):
    body = request.model_dump(mode="json",exclude_none=True)
    if request.request_id and key and str(request.request_id) != key:
        raise HTTPException(422, "request_id 与 Idempotency-Key 不一致")
    key = str(request.request_id) if request.request_id else key
    try:
        config, receipt = await admit(ctx,int(request.model[3:]),body,key,validate=video_options)
    except HTTPException as exc:
        if exc.status_code != 409 or not key:
            raise
        previous = await PlatformCallReceipt.get_or_none(dedup_key=digest([ctx.team_id,ctx.user.id,key]))
        if not previous or previous.pricing.get("type")!="video" or previous.payload_hash!=digest(body):
            raise
        prior_job = await PlatformVideoJob.get_or_none(receipt_id=previous.id)
        status = prior_job.status if prior_job else "queued"
        if previous.state in {"review","rejected"} and status!="completed":
            status="failed"
        return {"id":str(previous.public_id),"status":status}
    refs = request.references
    frames = {r.role:r.url for r in refs if r.role!="reference"}
    types = {kind:[r.url for r in refs if r.type==kind and r.role=="reference"] for kind in ("image","video","audio")}
    resolution = next(r for r in capabilities_for(config.video_model_type,config.api_protocol).resolutions
                      if r.lower()==request.resolution.lower())
    job = await PlatformVideoJob.create(receipt=receipt,route_hash=route_hash(config),inputs={
        "duration":request.duration, "resolution":resolution, "input_image_count":len(frames) + len(types["image"]),
        "has_video_reference":bool(types["video"])})
    from prompts.storyboard_sheet_binding import model_image_format
    label = model_image_format(config.video_model_type)
    prompt = re.sub(r"@image(\d+)", lambda m: label.format(int(m[1])), request.prompt)
    def media_label(match):
        kind, number = match.groups()
        if label.startswith("<Picture"):
            return f"<{kind.title()} {number}>"
        return ("@音频" if kind=="audio" else "@视频") + number
    prompt = re.sub(r"@(audio|video)(\d+)", media_label, prompt)
    try:
        async with asyncio.timeout(CALL_TIMEOUT):
            upstream_id = await get_generator(config).submit(prompt=prompt, duration=request.duration,
                resolution=resolution, aspect_ratio=request.aspect_ratio, output_format="mp4", generate_audio=request.generate_audio,
                return_last_frame=request.return_last_frame, generation_mode="keyframes" if frames else "reference",
                first_frame_url=frames.get("first_frame"),last_frame_url=frames.get("last_frame"),reference_images=types["image"],
                reference_videos=types["video"], reference_audios=types["audio"],team_id=ctx.team_id)
        if not upstream_id:
            raise ValueError("missing upstream task")
        await PlatformCallReceipt.filter(id=receipt.id,state="submitted").update(provider_id=upstream_id,state="processing")
    except (Exception, asyncio.CancelledError) as exc:
        definite = isinstance(exc,VideoProviderError) and not exc.submission_uncertain
        await PlatformCallReceipt.filter(id=receipt.id,state="submitted").update(state="rejected" if definite else "review")
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise HTTPException(422 if definite else 502,"未能确认视频提交，请凭请求编号核对",
                            headers={"X-Request-Id":str(receipt.public_id)}) from None
    return {"id":str(receipt.public_id),"status":job.status}


def nonnegative(value):
    return type(value) in {int,float} and isfinite(value) and value >= 0


def measured(inputs, metadata, rates):
    raw = metadata.get("usage") or {}
    seconds = metadata.get("duration")
    if seconds is None:
        seconds = inputs["duration"]  # Fixed-duration order; auto duration is not accepted here.
    if not nonnegative(seconds) or seconds <= 0:
        return None
    usage = {**inputs, "seconds":seconds, "duration_source":"provider" if metadata.get("duration") is not None else "order"}
    tokens = raw.get("completion_tokens") if isinstance(raw,dict) else None
    if rates.get("billing_unit") != "second" and type(tokens) is int and tokens > 0:
        return {**usage,"video_tokens":tokens}
    inp = raw.get("input_video_duration") if isinstance(raw,dict) else None
    if inputs["has_video_reference"] and not nonnegative(inp):
        return None
    return {**usage,"input_video_seconds":inp if inputs["has_video_reference"] else 0}


def video_cost(usage,rates):
    if "video_tokens" in usage:
        prices = (rates.get("video_reference_prices") or rates["prices"]) if usage["has_video_reference"] else rates["prices"]
        charge = Decimal(usage["video_tokens"]) * Decimal(str(prices[usage["resolution"]])) / Decimal(1000000)
        charge *= Decimal(str(rates.get("discount") or 1))
        return charge.quantize(Decimal("0.000001"),rounding=ROUND_HALF_UP) + compute_input_image_cost(usage["input_image_count"],rates)
    return compute_video_cost(usage["seconds"],usage["resolution"],rates,usage["input_video_seconds"],
                              usage["has_video_reference"],usage["input_image_count"])


async def refresh_job(job, receipt, *, renew=False):
    now = int(time.time())
    token = uuid4()
    statuses = ["completed"] if renew else ["queued", "in_progress"]
    claimed = await PlatformVideoJob.filter(id=job.id,status__in=statuses,poll_after__lte=now).update(
        poll_token=token,poll_after=now+100)
    if not claimed:
        return
    config = await AiModelConfig.get_or_none(id=receipt.model_config_id,scope="official",team_id__isnull=True)
    ours = PlatformVideoJob.filter(id=job.id,poll_token=token)
    if not config or route_hash(config)!=job.route_hash:
        if renew:
            await ours.update(poll_token=None, poll_after=now+60)
            return
        async with in_transaction():
            if await ours.update(status="failed",poll_token=None):
                await PlatformCallReceipt.filter(id=receipt.id,state="processing").update(state="review")
        return
    try:
        async with asyncio.timeout(90):
            result = await get_generator(config).query(receipt.provider_id)
        status = TaskStatusEnum(result["status"])
        metadata = result.get("metadata") or {}
        if renew and status != TaskStatusEnum.completed:
            await ours.update(poll_after=now+30,poll_token=None)
            return
        if status == TaskStatusEnum.completed:
            try:
                output = {"url":media_url(result.get("url"))}
                if metadata.get("last_frame_url"):
                    output["last_frame_url"] = media_url(metadata["last_frame_url"])
            except ValueError:
                if renew:
                    await ours.update(poll_after=now+30,poll_token=None)
                else:
                    async with in_transaction():
                        if await ours.update(status="failed",poll_token=None):
                            await PlatformCallReceipt.filter(id=receipt.id,state="processing").update(state="review")
                return
            if renew:
                await ours.update(output={**(job.output or {}),**output},poll_after=now+30,poll_token=None)
                return
            usage = measured(job.inputs,metadata,receipt.pricing)
            if usage:
                output["duration"] = usage["seconds"]
            async with in_transaction():
                if await ours.update(status="completed",progress=100,output=output,poll_after=now+15,poll_token=None):
                    await PlatformCallReceipt.filter(id=receipt.id,state="processing").update(
                        state="measured" if usage else "review", usage=usage)
            if usage:
                await settle(receipt.id)
        elif status in (TaskStatusEnum.failed,TaskStatusEnum.cancelled):
            async with in_transaction():
                if await ours.update(status="failed",poll_token=None):
                    await PlatformCallReceipt.filter(id=receipt.id,state="processing").update(state="rejected")
        else:
            await ours.update(status="queued" if status==TaskStatusEnum.queued else "in_progress",
                              progress=result.get("progress") or 0,poll_after=now+5,poll_token=None)
    except Exception:
        await ours.update(poll_after=int(time.time())+15,poll_token=None)
        logger.warning("Platform video status check deferred: receipt=%s",receipt.public_id)


async def video_status(ctx, public_id=None, key=None, *, refresh=False):
    lookup = {"dedup_key":digest([ctx.team_id,ctx.user.id,str(key)])} if key else {"public_id":public_id}
    receipt = await PlatformCallReceipt.get_or_none(team_id=ctx.team_id,user_id=ctx.user.id,**lookup)
    job = await PlatformVideoJob.get_or_none(receipt_id=receipt.id) if receipt else None
    if not job:
        raise HTTPException(404,"视频请求不存在")
    if receipt.state=="processing" or refresh and job.status=="completed":
        await refresh_job(job,receipt,renew=job.status=="completed")
        await job.refresh_from_db()
        await receipt.refresh_from_db()
    status = "failed" if job.status!="completed" and receipt.state in {"review","rejected"} else job.status
    return {"id":str(receipt.public_id),"status":status,"progress":job.progress,"metadata":job.output,
            "billing_status":receipt.state, **({"error":"视频任务失败或需要核对"} if status=="failed" else {})}


async def reconcile_videos():
    while True:
        try:
            jobs = await PlatformVideoJob.filter(status__in=["queued","in_progress"],receipt__state="processing",
                       poll_after__lte=int(time.time())).order_by("poll_after","id").limit(16).select_related("receipt")
            await asyncio.gather(*(refresh_job(job,job.receipt) for job in jobs))
        except Exception:
            logger.warning("Platform video reconciliation deferred")
        await asyncio.sleep(3)
