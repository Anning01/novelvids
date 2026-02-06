from fastapi import HTTPException

from models.chapter import Chapter
from services.nlp import RegexChapterRecognitionStrategy, NovelText
from utils.crud import CRUDBase
from models.novel import Novel
from schemas.novel import NovelCreate, NovelUpdate


class NovelController(CRUDBase[Novel, NovelCreate, NovelUpdate]):
    def __init__(self):
        super().__init__(model=Novel)

    async def update(self, novel_id: int, obj_in: NovelUpdate) -> Novel:
        instance = await self.get(novel_id)
        return await super().update(instance, obj_in)

    async def patch(self, novel_id: int, obj_in: NovelUpdate) -> Novel:
        instance = await self.get(novel_id)
        return await super().patch(instance, obj_in)

    async def remove(self, novel_id: int) -> None:
        instance = await self.get(novel_id)
        await super().remove(instance)

    async def split(self, novel_id: int):
        """使用nlp拆分章节"""
        # 使用 NLP 服务识别章节
        novel = await self.get(novel_id)

        # 如果已经有章节了，禁止使用此方法
        if await novel.chapters is None:
            raise HTTPException(400, detail="已有章节，不支持分章。")

        novel_text = NovelText.from_string(novel.content)
        service = RegexChapterRecognitionStrategy()
        parsed_chapters = service.recognize(novel_text)

        # 如果没有识别到章节，默认整个小说作为一个章节
        if not parsed_chapters:
            parsed_chapters = [
                type(
                    "ParsedChapterResult",
                    (),
                    {
                        "title": "第一章",
                        "content": novel.content,
                        "start_index": 0,
                        "end_index": len(novel.content),
                        "confidence": 1.0,
                    },
                )()
            ]

        # 创建章节记录
        for idx, chapter_result in enumerate(parsed_chapters):
            await Chapter.create(
                novel_id=novel.id,
                number=idx + 1,
                name=chapter_result.title,
                content=chapter_result.content,
            )

        # 更新小说的总章节数和状态
        await novel.update_from_dict(
            {
                "total_chapters": len(parsed_chapters),
            }
        )
        await novel.save()
        return novel


novel_controller = NovelController()
