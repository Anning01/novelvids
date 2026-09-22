"""Pure templates for story understanding and its optional cover."""
from prompts.extraction import SINGLE_CHARACTER_VISUAL_RULES
from utils.prompt_language import normalize_prompt_language, prompt_language_name


ANALYSIS_SYSTEM_PROMPT = """你是一名资深影视开发编辑。请严格依据给定书稿完成结构化分析，不要虚构书稿中不存在的剧情事实；人物必填视觉字段缺失时，按后述视觉规则结合小说语境进行克制、一致的设计推断。
类型标签应简洁准确；故事大纲应覆盖开端、主要冲突、关键转折和结局走向；关键人物只保留真正推动主线的人物。
人物的 chapter_numbers 必须使用材料中给出的章节序号。base_traits 必须使用任务指定的提示词语言，描述可见且相对稳定的外貌、服装和气质，便于后续生图。"""



def render_analysis_messages(*, name: str, chapter_count: int, material: str, prompt_language: str) -> list[dict[str, str]]:
    language_name = prompt_language_name(prompt_language)
    return [
        {"role": "system", "content": (
            f"{ANALYSIS_SYSTEM_PROMPT}\n"
            f"本任务的提示词语言是{language_name}；base_traits 必须严格使用该语言。\n\n"
            f"{SINGLE_CHARACTER_VISUAL_RULES.format(prompt_language_name=language_name)}"
        )},
        {"role": "user", "content": f"书名：《{name}》\n共 {chapter_count} 章。\n\n以下是书稿材料：\n{material}"},
    ]


def render_cover_prompt(*, name: str, book_types: list[str], story_outline: str, prompt_language: str = "en") -> str:
    types = "、".join(book_types)
    if normalize_prompt_language(prompt_language) == "en":
        return f"""Create a vertical cinematic short-drama cover key visual for the novel "{name}".
Genres: {types}.
Story outline: {story_outline}
Requirements: center the story's core conflict and atmosphere with cinematic composition and lighting; use a clear visual focal point suitable for a 2:3 vertical cover; do not include any text, title, subtitle, logo, watermark, or border; avoid distorted faces and extra limbs. Output at approximately 1K resolution."""
    return f"""为小说《{name}》创作一张竖版影视短剧封面主视觉。
题材：{types}。
故事大纲：{story_outline}
要求：以故事核心冲突和氛围为主体，电影级构图与光影，视觉焦点明确，适合 2:3 竖版封面；画面中不要出现任何文字、标题、字幕、Logo、水印或边框；避免人物面部畸变和多余肢体。按当前模型默认清晰度输出。"""
