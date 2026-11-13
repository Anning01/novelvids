"""Short-clip entry instructions; generation still uses the existing skill runtime."""
import json
import re
from prompts.skill_pack import read_skill, task_facts


def opening_message(*, mode, task_type, prompt, scene_id, asset_id, aspect_ratio, duration,
                    output_format='png', frame_count=None, frame_duration_ms=None):
    rule = json.loads(read_skill("clip_templates"))[mode]
    return rule + '\n' + task_facts({
        'user_idea': prompt, 'task_type': task_type, 'scene_id': scene_id,
        'reference_asset_id': asset_id, 'aspect_ratio': aspect_ratio,
        **({'output_format': 'gif', 'frame_count': frame_count, 'frame_duration_ms': frame_duration_ms}
           if output_format == 'gif' else {'duration': duration}),
    })


def with_references(prompt: str, markers: list[str]) -> str:
    return prompt + ('\n\n' + ' '.join(markers) if markers else '')


def render_named_references(prompt: str, bindings: dict[str, str]) -> str:
    """Compile exact display-name mentions without changing surrounding speech."""
    return re.sub(r"@\{([^{}]+)\}", lambda match: bindings.get(match[1], match[0]), prompt)
