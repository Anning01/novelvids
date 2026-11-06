"""Short-clip entry instructions; generation still uses the existing skill runtime."""
import re
from prompts.skill_pack import task_facts


def opening_message(*, mode, task_type, prompt, scene_id, asset_id, aspect_ratio, duration):
    rules = {
        'agent': '这是单次片段创作，不是连续剧。根据创意读取适用的图片或分镜技能，完善当前目标的完整生成提示词。不要拆章节或创建连续剧。必要时可设计参考图，但未授权的图片或视频生成先给出明确待确认操作。',
        'reference': '这是单次视频片段创作。读取图片和分镜技能，先完善已提供的画面参考资产与视频镜头提示词，再执行本轮授权的参考图生成。参考图应是完整的单幅电影画面，不是四宫格或三视图；视频必须沿用该参考画面。视频生成留待用户确认，不扩展为连续剧。',
    }
    return rules[mode] + '保留目标已有素材引用标记和绑定关系，参考素材不得作为视频里的文字。' + '\n' + task_facts({
        'user_idea': prompt, 'task_type': task_type, 'scene_id': scene_id,
        'reference_asset_id': asset_id, 'aspect_ratio': aspect_ratio, 'duration': duration,
    })


def with_references(prompt: str, markers: list[str]) -> str:
    return prompt + ('\n\n' + ' '.join(markers) if markers else '')


def render_named_references(prompt: str, bindings: dict[str, str]) -> str:
    """Compile exact display-name mentions without changing surrounding speech."""
    return re.sub(r"@\{([^{}]+)\}", lambda match: bindings.get(match[1], match[0]), prompt)
