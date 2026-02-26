from typing import List
from openai import AsyncOpenAI

from schemas.scene import SceneEntity, Storyboard


async def generate_storyboard(
    client: AsyncOpenAI,
    long_text: str,
    entities: List[SceneEntity],
    model: str
) -> tuple[Storyboard, dict]:
    """
    调用 OpenAI API 生成分镜板

    Returns:
        tuple[Storyboard, dict]: (生成的分镜板, 元数据字典)
    """
    # 构建实体上下文
    entities_context = ""
    for e in entities:
        entities_context += f"- Entity Name: {e.name}\n  Aliases: {', '.join(e.aliases)}\n  Visual Description: {e.description} (RULE: DO NOT re-describe this look, simply use @{{{e.name}}})\n\n"

    # 系统提示词 (System Prompt) - 融入了摄影指导思维
    system_prompt = f"""
You are an elite Cinematographer (DP) and Sora 2 Prompt Engineering Expert.
Your goal is to break down a narrative text into a "Sora 2 Ultra-Detailed Storyboard".

### 1. INPUT CONTEXT
- **Narrative**: A segment of a story.
- **Entities**: Pre-defined characters/places.

### 2. CRITICAL RULE: ENTITY BINDING
- When the narrative mentions a defined entity (or its alias), you MUST refer to it using the EXACT syntax `@{{EXACT Entity Name}}` with curly braces in `visual_prose` and `actions`.
- Entity names MUST be copied EXACTLY as listed below — do NOT abbreviate, truncate, or paraphrase them.
- Example: if entity is "Rabbit Cloth Doll", write `@{{Rabbit Cloth Doll}}`, NOT `@{{Rabbit Cloth}}` or `@{{Rabbit}}`.
- **NEVER** generate visual descriptions for `@{{Entity Name}}` (the rendering engine handles this).
- **ALWAYS** generate lavish, microscopic visual details for *anything else* (props, background textures, nameless extras).

### 3. SORA 2 "ULTRA-DETAILED" STYLE GUIDE
You must act like a film director using professional equipment. Fill the specific fields with technical jargon:
- **Format**: 180° shutter, Kodak Vision3, 65mm, coarse grain, halation, gate weave.
- **Lens**: 24mm/35mm/50mm/85mm primes, Anamorphic 2.0x, T1.5 aperture, Pro-Mist filters, Chromatic Aberration.
- **Lighting**: Chiaroscuro, Rembrandt, Sodium vapor practicals, Negative fill, Volumetric fog, God rays, 4x4 Bounce.
- **Grade**: Teal & Orange, Bleach bypass, Crushed blacks, Lifted shadows, Technicolor.
- **Sound**: Diegetic only. Mention LUFS levels, specific textures (leather creaking, snow crunching).

### 4. SHOT STRUCTURE
- Duration: Strictly 4s or 8s.
- Pacing: Break long scenes into multiple cuts.
- Actions: precise timestamps (0.0s-2.0s).

### DEFINED ENTITIES LIST
{entities_context}
"""

    user_prompt = f"""
### NARRATIVE TEXT TO PROCESS
\"\"\"
{long_text}
\"\"\"

Generate the storyboard now.
"""

    completion = await client.beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format=Storyboard,
        timeout=600,
        max_completion_tokens=10000  # o1 系列需要这个参数来增加输出长度
    )

    # 收集元数据
    metadata = {
        "model": completion.model,
        "response_id": completion.id,
        "created": completion.created,
        "system_fingerprint": getattr(completion, 'system_fingerprint', None),
    }

    # 添加 token 使用情况
    if hasattr(completion, 'usage') and completion.usage:
        usage = completion.usage
        metadata["usage"] = {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        }

        # 详细的 token 使用信息（如果有）
        if hasattr(usage, 'prompt_tokens_details') and usage.prompt_tokens_details:
            metadata["usage"]["prompt_tokens_details"] = usage.prompt_tokens_details.model_dump()
        if hasattr(usage, 'completion_tokens_details') and usage.completion_tokens_details:
            metadata["usage"]["completion_tokens_details"] = usage.completion_tokens_details.model_dump()

    # 检查是否有拒绝信息
    if hasattr(completion.choices[0].message, 'refusal') and completion.choices[0].message.refusal:
        metadata["refusal"] = completion.choices[0].message.refusal

    return completion.choices[0].message.parsed, metadata
