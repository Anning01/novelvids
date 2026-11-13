"""Project internal task diagnostics into actionable remake progress messages."""
import re
from uuid import uuid5

from models.agent_operation import AgentOperation
from models.creation_agent import AgentMessage
from utils.enums import TaskStatusEnum
from utils.messages import localized_message

_SEGMENT = re.compile(r'(?:第\s*(\d+)\s*个视频片段|Video segment\s+(\d+))', re.I)
_SERVICE_ERRORS = {
    'REMAKE_ANALYSIS_AUTH_FAILED': '视频分析服务未通过身份验证，请联系管理员检查模型密钥。',
    'REMAKE_MODEL_UNAVAILABLE': '请联系管理员配置可用的视频分析模型，然后重试。',
    'REMAKE_ANALYSIS_MODEL_NOT_FOUND': '请联系管理员配置可用的视频分析模型，然后重试。',
    'REMAKE_ANALYSIS_MODEL_TOOLS_REQUIRED': '请联系管理员配置可用的视频分析模型，然后重试。',
    'REMAKE_ANALYSIS_REQUEST_INVALID': '当前模型无法处理这段视频，请联系管理员检查视频分析模型。',
    'REMAKE_ANALYSIS_RATE_LIMITED': '视频分析服务正忙，请稍后重试。',
    'REMAKE_ANALYSIS_CONNECTION_FAILED': '暂时连不上视频分析服务，请稍后重试。',
    'REMAKE_ANALYSIS_PROVIDER_UNAVAILABLE': '视频分析服务暂时不可用，请稍后重试。',
    'REMAKE_MEDIA_WORKER_FAILED': '视频预处理失败，请联系管理员检查视频处理服务。',
}
_STAGES = {
    'preparing': '本集视频未能完成预处理，请重试。',
    'extracting_assets': '本集人物、场景和道具未能识别完成，请重试。',
    'detecting_scenes': '本集视频未能完成切镜，请重试。',
    'persisting': '本集拆解结果未能保存，请重试。',
}


async def failure_message(task):
    if task.status == TaskStatusEnum.cancelled:
        return localized_message('本集拆解已取消。')
    if task.status != TaskStatusEnum.failed:
        return None
    if task.stage == 'needs_review':
        return localized_message('尚未确认模型服务是否已受理本次拆解。请联系管理员核对，以免重复扣费。')
    diagnostic = task.error_message or ''
    for code, text in _SERVICE_ERRORS.items():
        if code in diagnostic:
            return localized_message(text)
    if 'insufficient_quota' in diagnostic or '可用额度不足' in diagnostic:
        return localized_message('视频分析账户的可用额度不足，请检查余额和限额后重试。')

    match = _SEGMENT.search(diagnostic)
    if match and task.stage == 'generating_storyboards':
        index = int(match[1] or match[2])
        reason = await _shot_reason(task.id, index)
        keys = await AgentOperation.filter(task=task, state='completed', key__startswith='model:remake:').values_list('key', flat=True)
        done = sorted(int(k.rsplit(':', 1)[1]) for k in keys if re.fullmatch(r'model:remake:RemakeShot:\d+', k))
        parts = [localized_message(reason, p0=index)]
        if 'model:remake:RemakeAssets:1' in keys:
            parts.append(localized_message('本集的人物、场景和道具设定已保留。'))
        if done:
            parts.append(localized_message('已保留 {p0} 个片段的分镜结果。', p0=len(done)))
        parts.append(localized_message('点击「重试」继续处理未完成的片段。'))
        return ' '.join(parts)
    return localized_message(_STAGES.get(task.stage, '本集拆解未完成，请重试。'))


async def _shot_reason(task_id, index):
    child = uuid5(task_id, f'model:remake:RemakeShot:{index}')
    messages = await AgentMessage.filter(task_id=child, role='assistant').values_list('native_messages', flat=True)
    for history in messages:
        for message in reversed(history or []):
            for part in message.get('parts', []):
                if part.get('part_kind') != 'retry-prompt':
                    continue
                issues = part.get('content')
                if isinstance(issues, list) and any(isinstance(i, dict) and 'same orientation' in str(i.get('msg', '')) for i in issues):
                    return '第 {p0} 个片段的空间定位图未能确认与场景底图方向一致，分镜未完成。'
                return '第 {p0} 个片段的分镜描述未通过检查。'
    return '第 {p0} 个片段未能完成分镜分析。'
