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



def cast_appearance_instruction(language):
    if language == "zh":
        return ("为每个人物、群像或动物在 appearances 中标出其实际出镜或发声的原片起止秒数。"
                "离场后再出现要分段列出；仅被提及、相似服装或同类身份都不能算作出场。")
    return ("For each character, group or animal, list its actual visible or speaking intervals in appearances "
            "using seconds from the start of the source. Split separate appearances. A mention, similar clothing "
            "or a similar role is not an appearance.")



def cast_reference_instruction(language):
    if language == "zh":
        return ("每个分镜的 asset_refs 都要列出实际出镜或发声的角色，即使项目目录暂为空。"
                "使用本镜内唯一的标识和可辨认的角色称呼，并在正文中沿用该称呼。仅被谈及的角色不计入。")
    return ("In each shot's asset_refs list every character actually seen or heard, even when the project catalog "
            "is empty. Use a shot-local ID and an identifiable character name consistently in the shot text. "
            "Omit characters who are only mentioned.")



def visual_asset_instruction(language, *, inventory):
    if inventory:
        return ("每个场景和道具都按原片秒数填写 appearances。记录真正入画的起止时间，切走后再次出现要分段。"
                "同一分镜可以切换布景；只在对白提及、只出现在图案中或仅可推断为附近的实物不算出镜。"
                if language == 'zh' else
                "For settings and props give actual on-screen source-time intervals in appearances. Split separate "
                "appearances, including setting changes within a shot. Mentions, depictions of a prop and objects "
                "merely inferred to be nearby do not establish that the physical object is on screen.")
    return ("每镜 asset_refs 也列出实际入画的场景和道具，使用 scene 或 object 类型。镜内转场、产品特写与片尾卡分开辨认。"
            if language == 'zh' else
            "Include each actually visible setting and prop in each shot's asset_refs with type scene or object. "
            "Identify changes of setting inside the shot, product close-ups and end cards.")


def source_handoff_instruction(language):
    if language == "zh":
        return ("每个给定区间是一条完整生成分镜，internal_cuts 是镜内切换，output_seconds 是成品整数秒数。"
                "动作、旁白和对白每行以原片绝对起止秒数开头，仅写该区间实际发生的部分；其余文字不写时间码。"
                "visual_prose 只写开场静态画面；transition 只写最后实际可见的状态、持物者及动作是否完成，不预演下一镜。"
                "换机位或场景时按本镜取景。先确定上一镜的结束状态再写本镜；有 confirmed_handoff 时以其中已完成动作为历史，不能再从头演。抛出已完成则下一镜从飞行或接住开始；若抛掷跨切点，只写剩余阶段。"
                "原片确有第二次抛掷才写第二次。内部切镜可为小数秒，总时长按 output_seconds。")
    return ("Each supplied interval is one generation shot. internal_cuts are edits within it; output_seconds "
            "is the whole-second target. Prefix each action, dialogue and narration line with its absolute source "
            "start and end seconds. Describe only its part in this interval. Use no timecodes elsewhere. "
            "visual_prose is the static opening frame. transition is the actual closing state, including possession "
            "and completed actions; do not preview the next shot. In a batch establish each ending before writing the next opening. Treat confirmed_handoff as history when supplied. A completed throw is history: continue with the "
            "object in flight or caught, without throwing it again. Keep genuine repetitions and only the remaining "
            "phase of a movement crossing a cut. Internal cuts can have fractional durations.")


def motion_memory_instruction(language, *, batch):
    if language == "zh":
        media = ("所附整片与全部区间共用一条原片时间轴。按镜号写齐，摄影风格可共用 looks。"
                 if batch else "最后一段是目标原片，前一段只供衔接。以 source_interval 起点换算原片绝对时间。")
        return (media + "每个 actions 条目是一次观察。start/end 是这个画面的原片绝对秒数，onset 是动作第一次实际起手的原片秒数。"
                "逐个核对相邻画面（含镜内换机位）：同一主体、动作、物体沿用同一 key；换机位、字幕变化和短暂遮挡均沿用原 onset。"
                "movement 写首次执行；continuation 只写新机位下已经保持的姿态、仍在进行的部分和新可见细节，包括字幕变化。"
                "同一动作只在原片看见收回、复位、第二次起手或明确回放时才换 onset，在 restart 写该证据的原片秒数 at 和可见事实 seen，否则填 null。"
                "独立动作拆成不同条目，即便它们同时发生。人物或物体不要互换。先观察前一画面末态，confirmed_handoff 仅作历史。"
                "visual_prose 写本镜第一帧，last_visible_state 只写本镜最后可见的物理状态，不预告下一画面。"
                "对白、旁白以原片绝对起止秒开头；sound_design.ambience 写底噪或音乐，cues 填原片绝对起止秒及音效，文字中不嵌入时间码。"
                "internal_cuts 是参考切点，保留其他实际换机位。output_seconds 是成品整数时长。"
                "照录原声，使用资产名称与本镜唯一的引用标识，小镜头如需 segments，沿用同一动作时间轴。")
    media = ("Use the attached full source and all numbered intervals on one absolute clock. Share looks across shots. "
             if batch else "The last clip is the target; preceding footage is continuity evidence. Add the source_interval origin to clip times. ")
    return (media + "For each observed action view, start/end are absolute source seconds and onset is the original physical start. "
            "Check every consecutive view including edits within a shot. Reuse the same actor/action/object key and onset when "
            "the camera angle or caption changes or the object briefly leaves view. movement describes initial execution; "
            "continuation describes only the remaining motion or held pose, new framing and newly visible detail, including captions. "
            "Only assign a new onset to the same motion when an observable reset, second start or intentional replay occurs; provide its absolute second (at) and visible evidence (seen) in restart, otherwise use null. "
            "Split independent actions even when simultaneous. Use the preceding end state and any confirmed_handoff as history. "
            "visual_prose is the first frame; last_visible_state is only the last visible physical state without previewing the next image. "
            "Prefix actual narration and dialogue with absolute source times. Use sound_design.ambience for background audio and cues for timed sounds with absolute start/end fields. No embedded timecodes in prose. "
            "internal_cuts are guide edits, preserve other actual changes of angle. output_seconds is the whole-second target. "
            "Transcribe actual speech, use shot-local unique asset references and use the same action timeline for optional segments.")


def timeline_instruction(language, *, batch):
    if language == 'zh':
        source = ('整片只附一次。按给定区间和镜号依次写：写本镜时参考刚写完的上一镜内容，已经演完的动作从其结果接起。' if batch else
                  '最后一段是本镜原片；前一段及 confirmed_handoff 仅供你辨认本镜开场状态。')
        return (source + '每条提示词都要能单独使用。所有可见字段直接写本镜的人物、画面、动作和声音；前情仅供分析，正文不复述上一镜，也不假设有尾帧参考图。'
                '在 actions 中按发生顺序写最终画面，每条只填原片绝对秒数 start、end 和要保存的 text。'
                '先看切点两边：谁持有什么、手停在哪里、物体还在移动还是已经停下。换角度、换景别或出现字幕时，'
                '承接已经完成的部分，只写新的视角、剩余动作和新变化。比如手已经递到对方面前，反打时写手仍举着和对方的反应。'
                '原片确有第二次起手就照实写。visual_prose 只写本镜开场，last_visible_state 只写末帧。'
                '声音底色写在 sound_design.ambience，音效和原片绝对起止秒写在 cues。旁白和对白按原声记录。'
                'asset_refs、dialogue、narration、last_visible_state 都是分镜字段，与 sound_design 同级。')
    source = ('Use the full source once. Write each numbered interval in order, using the immediately preceding generated shot as context. Start from the result of any completed action. '
              if batch else 'The last clip is the target. Use the preceding clip and any confirmed_handoff for its opening state. ')
    return (source + 'Each prompt must stand alone. Write only what is visible and audible in this shot. Prior context is for analysis; never recap the preceding shot or assume a tail-frame reference image. '
            'Write each final action in order as absolute source seconds start, end and the text to save. '
            'At each edit observe possession, hand position and motion on both sides. After a reverse angle, framing change or '
            'caption, describe the held state, remaining motion and new details. If a hand is already extended, show the '
            'held hand and the recipient’s reaction. Preserve actual second starts. visual_prose is the opening frame; '
            'last_visible_state is the final frame. Put background audio in sound_design.ambience and timed audio in cues '
            'using absolute source seconds. Transcribe actual speech. asset_refs, dialogue, narration and last_visible_state '
            'belong to the shot alongside sound_design.')

def registered_catalog_instruction(language):
    return ("assets 是本集已经提取的资产。对本镜实际出现的已登记主体，使用目录中的 id、name 和 type。"
            "目标视频第 0 秒对应 source_interval.start_seconds，动作和声音的原片时间按此起点换算。"
            if language == "zh" else
            "The assets catalog contains the registered subjects for this episode. Use the supplied id, name and type "
            "for each registered subject present in the target clip. Clip time zero corresponds to source_interval.start_seconds; "
            "use that offset for absolute action and sound times.")
