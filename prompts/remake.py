"""重制工坊视频拆解 Prompt 与严格 JSON 契约。

内容同步自 shengshimedia 无限画布复刻流水线；本模块保持无副作用，业务调用、
媒体加载、计费和持久化由 services/remake 负责。
"""

from typing import Any
from prompts.skill_pack import render_skill, task_facts


ASSET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "characters": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "label": {"type": "string", "enum": ["人物", "动物", "群像"]},
                    "description": {"type": "string"},
                },
                "required": ["name", "label", "description"],
            },
        },
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name", "description"],
            },
        },
        "objects": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name", "description"],
            },
        },
    },
    "required": ["characters", "scenes", "objects"],
}

for group in ASSET_SCHEMA['properties'].values():
    group['items']['properties']['visual_fields'] = {'type': 'object', 'additionalProperties': {'type': 'string'}}
    group['items']['required'].append('visual_fields')


DIALOGUE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "speaker_asset_id": {"type": "string"},
        "speaker_name": {"type": "string"},
        "delivery": {"type": "string"},
        "text": {"type": "string"},
    },
    "required": ["speaker_asset_id", "speaker_name", "delivery", "text"],
}

PROMPT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "asset_refs": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "asset_id": {"type": "string"},
                    "asset_name": {"type": "string"},
                    "asset_type": {
                        "type": "string",
                        "enum": ["character", "scene", "object"],
                    },
                },
                "required": ["asset_id", "asset_name", "asset_type"],
            },
        },
        "style": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "visual_style": {"type": "string"},
                "cinematography": {"type": "string"},
                "color_tone": {"type": "string"},
            },
            "required": ["visual_style", "cinematography", "color_tone"],
        },
        "global_conditions": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "time_weather": {"type": "string"},
                "environment_light": {"type": "string"},
                "spatial_relationships": {"type": "string"},
            },
            "required": ["time_weather", "environment_light", "spatial_relationships"],
        },
        "audio": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "has_bgm": {"type": "boolean"},
                "bgm_description": {"type": "string"},
            },
            "required": ["has_bgm", "bgm_description"],
        },
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "order": {"type": "integer"},
                    "start_seconds": {"type": "number"},
                    "end_seconds": {"type": "number"},
                    "title": {"type": "string"},
                    "camera": {"type": "string"},
                    "description": {"type": "string"},
                    "environment_sound": {"type": "string"},
                    "dialogues": {"type": "array", "items": DIALOGUE_SCHEMA},
                },
                "required": [
                    "order",
                    "start_seconds",
                    "end_seconds",
                    "title",
                    "camera",
                    "description",
                    "environment_sound",
                    "dialogues",
                ],
            },
        },
        "transition": {"type": "string"},
        "effects": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "forbidden": {"type": "string"},
                "allowed": {"type": "string"},
            },
            "required": ["forbidden", "allowed"],
        },
        "confidence": {"type": "number"},
    },
    "required": [
        "asset_refs",
        "style",
        "global_conditions",
        "audio",
        "shots",
        "transition",
        "effects",
        "confidence",
    ],
}


def render_remake_request(prompt, *, context, index, schema, include_segment_metadata, language="zh"):
    return prompt + "\n" + task_facts({"assets": context, "segment": index, "schema": schema})


def render_remake_prompt(kind: str, language: str) -> str:
    output_kind = 'global_key_assets' if kind == 'assets' else 'professional_video_prompt_material'
    return render_skill("remake", language, output_kind=output_kind)


def render_remake_catalog(assets: list[dict], language: str) -> str:
    return task_facts({"assets": assets})


def shot_continuity(previous, index, language):
    """Only carry the immediately preceding confirmed shot, never the prompt history."""
    context = {'sequence': index}
    for field in ('actions', 'dialogue', 'narration'):
        context[field] = [line[-500:] for line in (previous.get(field) or [])[-2:] if isinstance(line, str)]
    for field in ('visual_prose', 'spatial_relationships'):
        value = previous.get(field)
        if isinstance(value, str):
            context[field] = value[-600:]
    context['asset_refs'] = [{k: ref.get(k) for k in ('asset_id', 'asset_name', 'asset_type')}
                             for ref in previous.get('asset_refs', []) if isinstance(ref, dict)]
    return {'previous_shot': context, 'continuity_rule': continuity_instruction(language)}


def continuity_instruction(language):
    return ('上一镜是已确认的历史。只写本段视频里实际发生的动作和听到的对白，承接上一镜结束时的人物、道具状态。'
            '上一镜的开场布局不能代替结束状态。物体移出特写画框不等于已放下；本镜开场已经握住的物体，不要再写一次拿起或递出。以本段画面和原声为准。对白跨切口时，只记本段实际听到的部分；字幕若继续停留，不等于台词又说了一遍。原片确实重放或再次说出时保留。'
            if language == 'zh' else
            'The preceding shot is confirmed history. Describe only what is seen and heard in this clip. Carry forward the ending state. '
            'The prior opening layout is not its ending state. Leaving a close-up does not establish that an object was put down. If it is already held at the new opening, do not invent a second pickup or handoff. For speech across a cut, include only the words audible in this clip. A lingering subtitle is not a second utterance. Preserve actual replays and spoken repetitions.')


def identity_instruction(language):
    return ('这是同项目已登记的资产。只有身份明确、且在本集出现时才沿用标准名。不要复制未出镜资产；'
            '同名但不同身份或无法确定的主体用能区分的名称。明确的换装或形态可写为“主体名#形态名”，优先沿用已登记形态。' if language == 'zh' else
            'These assets belong to this project. Use the canonical name only when the identity is clear and present in this episode. '
            'Omit absent assets. Use distinct names for different or uncertain identities. For an explicit outfit or form, use canonical name#form name, reusing known forms.')


def project_asset_context(catalog, language):
    return {'project_assets': catalog, 'identity_rule': identity_instruction(language)}



def continuity_audit_facts(index, previous, draft, context, language):
    return {
        "segment": index,
        "preceding": shot_continuity(previous, index - 1, language)["previous_shot"],
        "candidate": {key: draft.get(key) for key in ("description", "actions", "spatial_relationships",
                                                       "visual_prose", "dialogue", "narration", "asset_refs")},
        "source_interval": context.get("source_interval"),
    }


def continuity_audit_instruction(language, *, parallel_drafts=False):
    if parallel_drafts:
        return ("对照相邻两镜的初稿摘要和本镜原片。检查本镜是否准确承接所给上一镜末态，是否错误重复或漏掉动作、对白和旁白。"
                "保留原片有意回放和跨切点的真实语音。只返回本镜能否按原样保留及简短依据。" if language == "zh" else
                "Compare the adjacent drafts using this clip and its audio. Check the transition from the supplied "
                "previous ending for missing or repeated actions and speech. Preserve intentional replays and speech "
                "that crosses the cut. Return whether this draft can stand unchanged and a short reason.")
    if language == "zh":
        return ("仅校对当前候选与真实上一镜的衔接。以附带的本镜原片和原声为准。核对已完成动作、人物/道具状态、"
                "对白与旁白是否被错误重演或漏掉；保留原片刻意回放及跨切口的真实语音。只返回是否可以原样保留及简短依据。")
    return ("Review only continuity against the confirmed predecessor and this clip's actual footage and sound. "
            "Check for replayed or missing actions, states, speech and narration. Preserve real replays and speech across cuts. "
            "Return whether the draft can be kept unchanged, with a short reason.")


def speech_boundary_instruction(language):
    if language == "zh":
        return ("只核听这一段原声。相邻两份分镜都写出了同一句话。只返回这句话在当前片段实际听见的字词，"
                "保留说出口的顺序，不补全上下句，不照抄延续显示的字幕。原声明确没有这句时返回空串；"
                "听不清、音轨不可用或无法判断时标记不确定。不要改写画面或续写剧情。")
    return ("Listen only to this clip's audio. Two neighboring drafts contain the same line. Return only the words "
            "of that line actually heard here, in order. Do not complete words from lingering subtitles or context. "
            "Use an empty string if the line is clearly absent. Mark uncertain if inaudible or indeterminate.")


def independent_shot_instruction(language):
    if language == 'zh':
        return ('所附最后一段视频是本镜原片。若有两段，第一段只供判断上一镜已发生的动作、对白和末态。'
                '只写目标片段实际发生和听到的内容，镜内时间从零计。保留真正重演的动作，跨切口的话按目标原声归属。'
                '项目目录仅供辨认。引用写出可确认的名称、类型和本镜内唯一标识；新出场主体也按所见记录。遵循现有输出协议，同一事实只描述一次。')
    return ('The last video is the target shot. If two are attached, the first shows only the preceding action, '
            'speech and ending state. Describe only what the target actually shows and sounds, starting at time zero. '
            'Keep genuine replays and attribute speech across the cut by its audio. Use the project catalog for '
            'recognition. Give each reference its observed name, type and a unique shot-local ID. Follow the output contract without restating facts.')



def parallel_identity_instruction(language):
    if language == "zh":
        return ("各集同时分析。跨集身份若能从原片明确确认，在 visual_fields 的 cross_episode_identity 记录关系及有名对象："
                "人物用 spouse:配偶姓名、parent:孩子姓名、child:父母姓名、sibling:兄弟姐妹姓名。"
                "地点仅用 address:确切地址，道具仅用 serial:原片可见的唯一编号。换装仍沿用同一身份。"
                "通用称呼、外貌、颜色、款式和猜测均不作为凭据，缺乏依据时省略该字段。")
    return ("Episodes are analyzed independently. Only for a source-confirmed identity, put cross_episode_identity "
            "in visual_fields. For people use spouse:<spouse name>, parent:<child name>, child:<parent name>, "
            "or sibling:<sibling name>. Keep it through outfit changes. "
            "For places use address:<exact address>; for objects use serial:<visible unique serial>. "
            "Omit the field if evidence is missing. Generic roles, appearance, color or product style do not identify a subject.")


def short_storyboard_instruction(language):
    if language == 'zh':
        return ('同一条原片只附一次。按给定的半开时间区间和镜号逐一写齐，上一段只用来衔接，保留原片真实的重复。'
                '每段各写一份可直接使用的简明提示词。每个描述字段用一句话写清可见事实，台词照录；动作、运镜和切换按段内时间描述。'
                '相同摄影风格写入 looks 一次，各镜按从 1 开始的序号引用，不同场景可用不同 look。'
                '只输出协议字段，不复述整版提示词，不展开额外的内部镜头表。')
    return ('The attached video is the entire source. Cover every supplied numbered half-open interval exactly once. '
            'Use adjacent footage for continuity, preserving genuine repeats. Write concise, usable material for '
            'each shot. Use a short sentence per descriptive field, transcribe actual speech, and place actions, camera moves and cuts in shot-local time. Put shared '
            'photographic settings once in looks, referenced by a 1-based index. Return only the contract fields.')
