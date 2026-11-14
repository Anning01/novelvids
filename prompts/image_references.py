"""Resolve editable reference markers against the submitted image order."""

import re


def render_image_reference_mentions(prompt: str, reference_count: int, language: str) -> str:
    def replace(match: re.Match) -> str:
        number = int(match[1])
        if not 1 <= number <= reference_count:
            raise ValueError("参考图片已移除，请重新选择引用")
        return f"参考图 {number}" if language == "zh" else f"reference image {number}"

    return re.sub(r"@\{参考图(\d+)\}", replace, prompt)


def render_identity_references(bindings: list[dict], language: str) -> str:
    if not bindings:
        return ''
    if language == 'zh':
        labels = '；'.join(f'参考图 {item["image_number"]}：{item["name"]}' for item in bindings)
        return (f'资产一致性参考：{labels}。以参考图保持同一资产的身份与识别特征，'
                '只按当前目标形态设定改变年龄、服饰、材质或状态；未要求改变的特征保持一致。'
                '参考图中的年龄与装束不能覆盖当前目标形态设定。')
    labels = '; '.join(f'reference image {item["image_number"]}: {item["name"]}' for item in bindings)
    return (f'Asset identity references: {labels}. Preserve the same identity and identifying features. '
            'Change age, clothing, material or state only as specified by the target design. '
            'Reference age and clothing must not override the target form.')
