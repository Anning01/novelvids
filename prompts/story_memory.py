"""Story memory for downstream creative context."""

from schemas.story_memory import StoryMemoryNote

CONTRACT_VERSION = 2

EXTRACT = """只输出 summary，用几句话写成供下一次创作直接使用的故事记忆，通常两小段即可。
全局底稿：从项目设定、大纲与开篇提炼基础世界观，写清有依据的年代、社会环境、科技或生活条件，以及故事主线。大纲计划明确标为计划，开篇经历只作为起点。
章节记忆：以本章剧本或原文为准，参照全局底稿、最近有效章节记忆及前章片段，写出当前世界与阶段。延续仍有效的关键设定、人物身份和因果，用简短记叙更新已经发生的变化与章末状态。
世界发生切换时说明前一世界、转变原因（如已知）与当前世界。回忆、梦境或同章多世界按场景区分；同一世界的灾变可描述为阶段变化。
区分已发生的事、人物推测和未执行的计划。保持原文与改编设定的区别。未知的年代、职业、穿着保持未知；切勿从书名、资产或分镜补造事实。
只选会影响后续创作的内容。不要逐条列证据、计算位置、生成标识或罗列未知项。"""


def method(selected, language):
    instructions = EXTRACT + '\n任务语言 language=' + language
    if selected.get('builtin'):
        return {'instructions': instructions, 'references': []}
    if selected['instructions']:
        instructions += '\n补充分析方法：\n' + selected['instructions']
    return {**selected, 'instructions': instructions}


def contract():
    return {'name': 'story_memory_extract', 'version': CONTRACT_VERSION, 'schema': StoryMemoryNote.model_json_schema()}
