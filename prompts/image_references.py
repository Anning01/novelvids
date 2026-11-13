"""Resolve editable reference markers against the submitted image order."""

import re


def render_image_reference_mentions(prompt: str, reference_count: int, language: str) -> str:
    def replace(match: re.Match) -> str:
        number = int(match[1])
        if not 1 <= number <= reference_count:
            raise ValueError("参考图片已移除，请重新选择引用")
        return f"参考图 {number}" if language == "zh" else f"reference image {number}"

    return re.sub(r"@\{参考图(\d+)\}", replace, prompt)
