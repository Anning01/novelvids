"""Expose persisted story results independently from an optional cover failure."""

from pydantic import ValidationError

from models.agent_operation import AgentOperation
from models.ai_task import AiTask
from utils.messages import localized_message


def cover_warning(language: str | None = None) -> str:
    return localized_message('故事分析已完成，封面暂未生成。已保存的类型、大纲和人物可以继续使用。', _language=language)


async def expose_saved_analysis(task: AiTask | None) -> AiTask | None:
    if task is None or not task.response_data or task.response_data.get('analysis_completed'):
        return task
    # Old failures already saved story results before attempting the cover.
    # Read projection only: the original media receipt and accounting state stay intact.
    if task.status != 4 or not await AgentOperation.filter(task=task, key='persist:story', state='completed').exists():
        return task
    from services.project_analysis.handler import BookAnalysis

    try:
        BookAnalysis.model_validate(task.response_data)
    except ValidationError:
        return task
    uncertain = await AgentOperation.filter(task=task, key__in=['media:cover', 'model:image:CompletePrompt:'], state='uncertain', external=True).exists()
    task.response_data = {**task.response_data, 'analysis_completed': True,
        'cover_status': 'needs_review' if uncertain else 'failed',
        'cover_warning': cover_warning(task.request_params.get('prompt_language', 'en'))}
    return task
