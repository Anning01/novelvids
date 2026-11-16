"""Pure rendering for reference-based storyboard sheet edits."""
import json


def render_sheet_edit(original_prompt: str, instruction: str, language: str) -> str:
    rule = (
        'Edit reference image 1, the existing storyboard sheet. Apply the requested change to that sheet. '
        'Preserve its panel count, order, composition, characters and line-art style unless the request explicitly changes them. '
        'Copy any text explicitly requested by the user verbatim, including apparent typos. The requested change overrides conflicting original text. '
        'Return one complete edited sheet. Do not add captions, labels, borders or watermarks that were not requested.'
        if language == 'en' else
        '编辑参考图1：它是本分镜现有的线稿故事版。按本次修改要求编辑这张图。'
        '除非用户明确要求改变，否则保留原图画格数量、顺序、构图、人物及线稿风格，只调整要求修改的部分。'
        '用户明确指定写入的字样必须逐字保留，包括看似错字的文字，不按原提示词或已有设定擅自纠正；冲突时以本次要求为准。'
        '返回一张完整的修改后线稿，不添加未经要求的说明文字、标签、边框或水印。'
    )
    return rule + '\n\n' + json.dumps({'original_prompt': original_prompt, 'requested_change': instruction}, ensure_ascii=False)
