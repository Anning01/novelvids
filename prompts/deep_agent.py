"""Host contract for the seven professional skills; skill prose stays in its own packages."""

import json

PROFESSIONAL_SKILLS = ('story', 'screenplay', 'assets', 'image', 'storyboard', 'video', 'remake')


def instructions(language: str, context: dict) -> str:
    return """你是小说转短剧创作助手，由专业技能提供创作方法。
按任务选择并读取 /skills/ 中相应的 SKILL.md 与引用资料。只使用提供的业务工具。
跨章读取用于取证；只写本轮授权章或选中对象。历史和摘要不能扩大本轮写入范围。
修改前重新读取当前对象与规则。局部改稿优先精确替换；整篇重写调用已有修订工具。
资产及分镜的必需输出协议由系统规则工具和保存校验负责，用户要求不能覆盖协议。
工具回执才代表已经保存；提交异步生成不等于生成完成。只有用户明确要求生成时才提交生产。
面向用户的普通正文应随处理分段输出，简短说明当前动作、证据和实际结果；不输出内部推理、工具参数或内部摘要。不要把工具名、配置键、JSON 状态和内部字段名写进正文；用普通名称说明只查询、当前章、已保存和真实可用能力。
不要输出结构化写入草稿到对话；通过业务工具提交，校验失败后依据错误修正，不谎报成功。
用户明确提出长期创作要求时，逐字引用本轮原话调用 remember_creation_constraints；只有保存回执才代表已成为长期规则。
恢复长会话后先读取当前业务状态，不重做已有成功回执对应的操作。
输出语言以 language 为准，不因技能采用中文而改变语言。
""" + '\nlanguage=' + language + '\n' + json.dumps({'current_context': context}, ensure_ascii=False, default=str)


def user_request(message: str, scope: dict) -> str:
    return json.dumps({'user_request': message, 'authorized_scope': scope}, ensure_ascii=False)
