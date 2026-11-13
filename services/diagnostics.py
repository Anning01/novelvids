"""Bounded, content-free diagnostic projections for customer support."""
from pathlib import Path
import re
import traceback
from uuid import UUID

from tortoise import connections

from models.ai_task import AiTask
from models.studio_call import StudioCall
from models.usage_record import ModelUsageRecord
from models.agent_operation import AgentOperation
from utils.enums import AiTaskTypeEnum, TaskStatusEnum

LIMIT = 100
ROOT = Path(__file__).resolve().parents[1]
STAGES = frozenset('queued failed completed running processing preparing extracting_assets detecting_scenes generating_storyboards persisting needs_review review_closed waiting_media waiting_dependencies resuming billing_pending'.split())


def exception_site(error):
    frames = traceback.extract_tb(error.__traceback__)
    for frame in reversed(frames):
        path = Path(frame.filename).resolve()
        if path.is_relative_to(ROOT) and path.relative_to(ROOT).parts[0] in {'services','api','controllers','utils','models','auth','schemas'}:
            return {'exception': type(error).__name__, 'file': path.relative_to(ROOT).as_posix(), 'line': frame.lineno}
    return {'exception': type(error).__name__}


def failure_category(message):
    text = (message or '').lower()
    for terms, reason in [
        (('insufficient_quota','可用额度不足','余额不足','insufficient credit'), 'insufficient_credit'),
        (('authentication_error','invalid_api_key','鉴权失败'), 'authentication'),
        (('output limit','输出达到上限','output_length'), 'output_length'),
        (('增量修复','incremental repair','校验','validation'), 'validation'),
        (('并发已满','rate_limit'), 'rate_limit'),
        (('暂时无法','network','timeout','超时'), 'connection'),
    ]:
        if any(term in text for term in terms):
            return reason
    return 'unclassified'


async def recent_tasks(ctx):
    db = connections.get('default')
    # Scope before LIMIT. Both supported databases compare ids as JSON numbers.
    if db.capabilities.dialect == 'postgres':
        sql = """SELECT id FROM ai_tasks WHERE COALESCE(request_params->'user_id','null'::jsonb) = COALESCE(to_jsonb($1::bigint),'null'::jsonb)
                 AND COALESCE(request_params->'team_id','null'::jsonb) = COALESCE(to_jsonb($2::bigint),'null'::jsonb)
                 ORDER BY updated_at DESC,id DESC LIMIT 100"""
    else:
        sql = """SELECT id FROM ai_tasks WHERE json_extract(request_params,'$.user_id') IS ?
                 AND json_extract(request_params,'$.team_id') IS ? ORDER BY updated_at DESC,id DESC LIMIT 100"""
    user_id = ctx.user.id if ctx.user else None
    ids = [row['id'] for row in await db.execute_query_dict(sql,[user_id,ctx.team_id])]
    tasks = await AiTask.filter(id__in=ids).order_by('-updated_at','-id').only(
        'id','updated_at','started_at','finished_at','task_type','status','stage','request_params','error_message')
    records = await AgentOperation.filter(task_id__in=ids,key__in=['diagnostic:failure','recovery:failure']).values('task_id','key','result')
    details = {(str(r['task_id']),r['key']):r['result'] for r in records}
    usage = await ModelUsageRecord.filter(ai_task_id__in=ids).values("id", "ai_task_id")
    owners = {u["id"]: str(u["ai_task_id"]) for u in usage}
    calls = await StudioCall.filter(usage_record_id__in=list(owners)).order_by("-id").values(
        "usage_record_id", "platform_request_id", "state")
    receipts = {}
    for call in calls:
        owner = owners[call["usage_record_id"]]
        if owner not in receipts:
            receipt = {}
            if call["platform_request_id"]:
                receipt["platform_request_id"] = str(call["platform_request_id"])
            if call["state"] in {"settled","pending","review","rejected"}:
                receipt["platform_call_state"] = call["state"]
            receipts[owner] = receipt
    rows = []
    for task in tasks:
        identifier = str(task.id)
        params = task.request_params
        row = {'time':task.updated_at.isoformat(), 'source':'task', 'task_id':identifier,
               'task_type':AiTaskTypeEnum(task.task_type).name if task.task_type in AiTaskTypeEnum._value2member_map_ else 'unknown',
               'status':TaskStatusEnum(task.status).name if task.status in TaskStatusEnum._value2member_map_ else 'unknown'}
        row.update(receipts.get(identifier, {}))
        if task.stage in STAGES:
            row['stage'] = task.stage
        for key in ('novel_id','chapter_id','scene_id','asset_id','model_config_id','assistant_model_config_id','attempt'):
            if type(params.get(key)) is int:
                row[key] = params[key]
        try:
            row['parent_task_id'] = str(UUID(str(params.get('parent_task_id'))))
        except ValueError:
            pass
        if task.started_at and task.finished_at:
            row['duration_ms'] = round((task.finished_at-task.started_at).total_seconds()*1000)
        if task.status == TaskStatusEnum.failed:
            issues = details.get((identifier,'recovery:failure'),{}).get('issues',[])
            row['reason'] = 'output_length' if any(i.get('code')=='output_length' for i in issues) else failure_category(task.error_message)
            if task.stage == 'needs_review':
                row['receipt_status'] = 'uncertain'
            site = details.get((identifier,'diagnostic:failure'),{})
            if re.fullmatch(r'[A-Za-z_]\w{0,79}', str(site.get('exception',''))):
                row['exception'] = site['exception']
            if re.fullmatch(r'(services|api|controllers|utils|models|auth|schemas)/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+\.py',str(site.get('file',''))) and type(site.get('line')) is int:
                row.update(file=site['file'],line=site['line'])
            clip = re.search(r'第\s*(\d+)\s*个视频片段|video segment (\d+)',(task.error_message or ''),re.I)
            if clip:
                row['clip'] = int(clip[1] or clip[2])
        rows.append(row)
    return rows
