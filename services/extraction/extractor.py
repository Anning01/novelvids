"""人物/场景/物品提取器。

使用 OpenAI 结构化输出（response_format），直接返回 Pydantic 模型。
不涉及数据库操作，调用方自行处理存储。

用法：
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key="sk-xxx", base_url="https://...")
    extractor = PersonExtractor(client, model="gpt-4o-mini")
    result = await extractor.extract("小说文本...", chapter_number=1)
    # result.persons -> list[Person]
"""

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from prompts.extraction import (
    ITEM_EXTRACTION_PROMPT,
    ITEM_SYSTEM_PROMPT,
    PERSON_EXTRACTION_PROMPT,
    PERSON_SYSTEM_PROMPT,
    SCENE_EXTRACTION_PROMPT,
    SCENE_SYSTEM_PROMPT,
)



# ---- 结构化输出模型 ----

class Appearance(BaseModel):
    line: int = Field(description="出现的行号")
    context: str = Field(description="出现的上下文")


class Person(BaseModel):
    name: str = Field(description="标准名称")
    aliases: list[str] = Field(default_factory=list, description="别名列表")
    description: str = Field(description="中文描述：性格、身份、背景等")
    base_traits: str = Field(description="详细英文视觉描述，用于AI图像生成")
    appearances: list[Appearance] = Field(default_factory=list, description="出现位置")


class Scene(BaseModel):
    name: str = Field(description="场景名称")
    aliases: list[str] = Field(default_factory=list, description="别名列表")
    description: str = Field(description="中文描述：环境、氛围、特点等")
    base_traits: str = Field(description="详细英文视觉描述，用于AI图像生成")
    appearances: list[Appearance] = Field(default_factory=list, description="出现位置")


class Item(BaseModel):
    name: str = Field(description="物品名称")
    aliases: list[str] = Field(default_factory=list, description="别名列表")
    description: str = Field(description="中文描述：外观、功能、来源等")
    base_traits: str = Field(description="详细英文视觉描述，用于AI图像生成")
    appearances: list[Appearance] = Field(default_factory=list, description="出现位置")


class PersonList(BaseModel):
    persons: list[Person]


class SceneList(BaseModel):
    scenes: list[Scene]


class ItemList(BaseModel):
    items: list[Item]


# ---- 提取器 ----

class BaseExtractor:
    """提取器基类。子类定义 prompt 和 response_model 即可。"""

    system_prompt: str = ""
    user_prompt_template: str = ""
    response_model: type[BaseModel]

    def __init__(self, client: AsyncOpenAI, model: str = "gpt-4o-mini", max_text_length: int = 8000):
        self.client = client
        self.model = model
        self.max_text_length = max_text_length

    async def extract(self, text: str, chapter_number: int) -> BaseModel:
        """提取实体，直接返回结构化的 Pydantic 模型。"""
        prompt = self.user_prompt_template.format(
            chapter_number=chapter_number,
            text=text[:self.max_text_length],
        )

        response = await self.client.beta.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            response_format=self.response_model,
        )

        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError("LLM 返回结果解析失败")
        return parsed


class PersonExtractor(BaseExtractor):
    system_prompt = PERSON_SYSTEM_PROMPT
    user_prompt_template = PERSON_EXTRACTION_PROMPT
    response_model = PersonList


class SceneExtractor(BaseExtractor):
    system_prompt = SCENE_SYSTEM_PROMPT
    user_prompt_template = SCENE_EXTRACTION_PROMPT
    response_model = SceneList


class ItemExtractor(BaseExtractor):
    system_prompt = ITEM_SYSTEM_PROMPT
    user_prompt_template = ITEM_EXTRACTION_PROMPT
    response_model = ItemList
