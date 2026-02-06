"""章节识别策略模块。

提供多种章节识别策略：
- RegexChapterRecognitionStrategy: 基于正则表达式的识别
- MLChapterRecognitionStrategy: 基于机器学习的识别
"""

import re
from abc import ABC, abstractmethod
from decimal import Decimal, getcontext


from dataclasses import dataclass
from typing import Self


@dataclass(frozen=True)
class NovelText:
    """表示原始小说文本的值对象。"""

    content: str

    @property
    def length(self) -> int:
        """获取内容长度。"""
        return len(self.content)

    def is_empty(self) -> bool:
        """检查内容是否为空。"""
        return not self.content.strip()

    @classmethod
    def from_string(cls, content: str) -> Self:
        """从字符串创建实例。"""
        if not content:
            raise ValueError("小说内容不能为空")
        return cls(content=content)


@dataclass(frozen=True)
class ParsedChapterResult:
    """表示识别出的章节的值对象。"""

    title: str
    content: str
    start_index: int
    end_index: int
    confidence: float = 1.0

    def __post_init__(self):
        """验证索引值。"""
        if self.start_index < 0:
            raise ValueError("起始索引不能为负数")
        if self.end_index <= self.start_index:
            raise ValueError("结束索引必须大于起始索引")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("置信度必须在 0.0 到 1.0 之间")


# 中文数字映射表
CN_NUM = {
    "〇": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "零": 0,
    "壹": 1,
    "贰": 2,
    "叁": 3,
    "肆": 4,
    "伍": 5,
    "陆": 6,
    "柒": 7,
    "捌": 8,
    "玖": 9,
    "貮": 2,
    "两": 2,
}

# 中文数字单位映射表
CN_UNIT = {
    "十": 10,
    "拾": 10,
    "百": 100,
    "佰": 100,
    "千": 1000,
    "仟": 1000,
    "万": 10000,
    "萬": 10000,
    "亿": 100000000,
    "億": 100000000,
    "兆": 1000000000000,
}


def chinese2digit(chinese_number: str) -> Decimal | int:
    """
    将中文数字字符串转换为数字。

    参数：
        chinese_number: 中文数字字符串

    返回：
        转换后的数字（Decimal 或 int 类型）
    """
    chinese_number_list = chinese_number.split("点")
    integer = list(chinese_number_list[0])  # 整数部分
    decimal = (
        list(chinese_number_list[1]) if len(chinese_number_list) == 2 else []
    )  # 小数部分
    unit = 0
    parse = []

    while integer:
        number = integer.pop()
        if number in CN_UNIT:
            unit = CN_UNIT.get(number)
            if unit == 10000:
                parse.append("w")
                unit = 1
            elif unit == 100000000:
                parse.append("y")
                unit = 1
            elif unit == 1000000000000:
                parse.append("z")
                unit = 1
        else:
            dig = CN_NUM.get(number)
            if unit:
                dig = dig * unit
                unit = 0
            parse.append(dig)

    if unit == 10:
        parse.append(10)

    result = 0
    tmp = 0
    while parse:
        number = parse.pop()
        if number == "w":
            tmp *= 10000
            result += tmp
            tmp = 0
        elif number == "y":
            tmp *= 100000000
            result += tmp
            tmp = 0
        elif number == "z":
            tmp *= 1000000000000
            result += tmp
            tmp = 0
        else:
            tmp += number
    result += tmp

    if decimal:
        unit = 0.1
        getcontext().prec = len(decimal)
        result = Decimal(float(result))
        tmp = Decimal(0)
        for each in decimal:
            dig = CN_NUM.get(each)
            tmp += Decimal(str(dig)) * Decimal(str(unit))
            unit *= 0.1
        getcontext().prec = len(result.to_eng_string()) + len(decimal)
        result += tmp

    return result


class ChapterRecognitionStrategy(ABC):
    """章节识别策略的抽象基类。"""

    @abstractmethod
    def recognize(self, text: NovelText) -> list[ParsedChapterResult]:
        """
        从小说文本中识别章节。

        参数：
            text: 要处理的小说文本

        返回：
            识别出的章节列表
        """
        pass


class RegexChapterRecognitionStrategy(ChapterRecognitionStrategy):
    """基于正则表达式的章节识别策略。"""

    # 匹配 "第X章"，X 可以是中文数字或阿拉伯数字
    # 捕获组: (完整匹配), (数字部分), (标题部分)
    CHAPTER_PATTERN = re.compile(
        r"^\s*(第\s*([0-9零一二三四五六七八九十百千万亿]+)\s*章)(.*)", re.MULTILINE
    )

    def recognize(self, text: NovelText) -> list[ParsedChapterResult]:
        """使用正则表达式和中文数字转换识别章节。"""
        if text.is_empty():
            return []

        chapters: list[ParsedChapterResult] = []
        matches = list(self.CHAPTER_PATTERN.finditer(text.content))

        for i, match in enumerate(matches):
            chapter_marker = match.group(1)  # "第X章"
            title_suffix = match.group(3).strip()  # 标题

            # 组合完整标题
            full_title = f"{chapter_marker} {title_suffix}".strip()

            start_index = match.start()

            # 结束索引为下一个匹配的开始位置或字符串末尾
            if i + 1 < len(matches):
                end_index = matches[i + 1].start()
            else:
                end_index = text.length

            # 提取章节内容（从匹配结束位置到下一章开始）
            content_start = match.end()
            chapter_content = text.content[content_start:end_index].strip()

            # 正则匹配的置信度为 1.0
            chapters.append(
                ParsedChapterResult(
                    title=full_title,
                    content=chapter_content,
                    start_index=start_index,
                    end_index=end_index,
                    confidence=1.0,
                )
            )

        return chapters


class Pattern:
    """章节匹配模式生成器。"""

    def __init__(self) -> None:
        self.prefix = r"第"
        self.body = r"\d一二三四五六七八九十零〇百千两"
        self.suffix = r"第章回部节集卷"
        self.tail = r" |、|，|\S"
        self.interval = r" *"
        self.digit_rule = r"\d"
        self.chinese_rule = r"一二三四五六七八九十零〇百千两"

    def get_global_pattern(self) -> str:
        """
        获取用于从文本中提取章节名的全局匹配模式。

        返回：
            正则表达式模式字符串
        """
        pattern = r"[" + self.prefix + r"]"
        pattern = pattern + self.interval
        pattern = pattern + r"[" + self.body + r"]" + "+"
        pattern = pattern + self.interval
        pattern = pattern + r"[" + self.suffix + r"]"
        pattern = pattern + r"(" + self.tail + r")"

        return pattern

    def get_digit_number_from_chapter(self) -> str:
        """
        获取用于从章节名中提取阿拉伯数字的模式。

        返回：
            正则表达式模式字符串
        """
        pattern = r"[" + self.digit_rule + r"]" + "+"

        return pattern

    def get_chinese_number_from_chapter(self) -> str:
        """
        获取用于从章节名中提取中文数字的模式。

        返回：
            正则表达式模式字符串
        """
        pattern = r"[" + self.chinese_rule + r"]" + "+"

        return pattern


class MLChapterRecognitionStrategy(ChapterRecognitionStrategy):
    """基于机器学习（零样本分类）的章节识别策略。"""

    def __init__(self, model_name: str = "typeform/distilbert-base-uncased-mnli"):
        """
        使用指定模型初始化 ML 策略。

        参数：
            model_name: Hugging Face 模型名称
        """
        try:
            from transformers import pipeline

            self.classifier = pipeline("zero-shot-classification", model=model_name)
        except ImportError:
            raise ImportError(
                "MLChapterRecognitionStrategy 需要 transformers 包。"
                "请使用 `pip install transformers` 安装。"
            )
        self.pattern = Pattern()

    def _processing_priority(
        self, line: str, instance_index: int = 0
    ) -> tuple[int | Decimal, int]:
        """
        使用模式确定章节序号。

        参数：
            line: 要处理的文本行
            instance_index: 实例索引，用于确定优先使用阿拉伯数字还是中文数字

        返回：
            (章节序号, 更新后的实例索引)
        """
        if instance_index == 0:
            chapter_match_ = re.search(
                self.pattern.get_digit_number_from_chapter(), line
            )
            if not chapter_match_:
                chapter_match_ = re.search(
                    self.pattern.get_chinese_number_from_chapter(), line
                )
                instance_index = 1
                if chapter_match_:
                    current_chapter_match = chinese2digit(chapter_match_[0])
                else:
                    current_chapter_match = 0
            else:
                current_chapter_match = int(chapter_match_[0])
            return current_chapter_match, instance_index
        else:
            chapter_match_ = re.search(
                self.pattern.get_chinese_number_from_chapter(), line
            )
            if not chapter_match_:
                chapter_match_ = re.search(
                    self.pattern.get_digit_number_from_chapter(), line
                )
                instance_index = 0
                if chapter_match_:
                    current_chapter_match = int(chapter_match_[0])
                else:
                    current_chapter_match = 0
            else:
                if chapter_match_:
                    current_chapter_match = chinese2digit(chapter_match_[0])
                else:
                    current_chapter_match = 0
            return current_chapter_match, instance_index

    def recognize(self, text: NovelText) -> list[ParsedChapterResult]:
        """
        使用 ML 分类识别章节。

        此方法逐行扫描文本以查找章节标题：
        1. 首先使用全局模式匹配
        2. 使用分类器验证
        3. 提取章节序号用于顺序验证

        参数：
            text: 要处理的小说文本

        返回：
            识别出的章节列表
        """
        if text.is_empty():
            return []

        chapters: list[ParsedChapterResult] = []
        lines = text.content.splitlines()

        chapter_index = 0
        instance_index = 0

        # 临时存储找到的章节元数据
        found_chapters_meta = []

        # 当前字符偏移量
        current_char_offset = 0

        for i, line in enumerate(lines):
            line_len = len(line) + 1  # +1 为换行符
            line_stripped = line.rstrip("\r\n")

            chapter_candidate = re.search(
                self.pattern.get_global_pattern(), line_stripped
            )

            if chapter_candidate:
                # 找到潜在的章节标题
                result = self.classifier(
                    line_stripped, candidate_labels=["Chapter", "Not Chapter"]
                )
                chapter_score = (
                    result["scores"][0] if result["labels"][0] == "Chapter" else 0
                )

                sequential_bonus = 0
                current_chapter_number, instance_index = self._processing_priority(
                    line_stripped, instance_index
                )

                # 如果章节序号连续，给予额外分数
                if current_chapter_number == chapter_index + 1:
                    sequential_bonus = 0.1

                final_score = chapter_score + sequential_bonus

                if final_score > 0.7:
                    # 确认找到章节
                    chapter_index = (
                        current_chapter_number
                        if isinstance(current_chapter_number, int)
                        else int(current_chapter_number)
                    )

                    # 如果不是第一章，需要关闭前一章
                    if found_chapters_meta:
                        prev = found_chapters_meta[-1]
                        prev["end_index"] = current_char_offset

                    found_chapters_meta.append(
                        {
                            "title": line_stripped,
                            "start_index": current_char_offset,
                            "end_index": -1,  # 将由下一章或文件末尾设置
                            "confidence": float(final_score),
                        }
                    )

            current_char_offset += line_len

        # 关闭最后一章
        if found_chapters_meta:
            found_chapters_meta[-1]["end_index"] = text.length

        # 构建结果对象
        for meta in found_chapters_meta:
            content = text.content[meta["start_index"] : meta["end_index"]].strip()

            chapters.append(
                ParsedChapterResult(
                    title=meta["title"],
                    content=content,
                    start_index=meta["start_index"],
                    end_index=meta["end_index"],
                    confidence=meta["confidence"],
                )
            )

        return chapters
