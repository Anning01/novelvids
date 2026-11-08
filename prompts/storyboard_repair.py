"""Model-facing instructions for bounded storyboard patches."""

import json


def structural_repair(language, checkpoint):
    text = (
        'Return only corrected shots for pending original shot numbers. Set repair_of on every returned shot. '
        'To split one shot, return multiple shots with the same repair_of, in story order. '
        'The server retains all accepted shots; do not repeat, renumber or rewrite them. '
        'Preserve the failed shot’s complete speech, speakers and order; only fix timing, structure or references. '
        'Each split shot starts its timeline at zero.\n'
        if language == 'en' else
        '只返回 pending 中出错镜头的修正版，每条必须用 repair_of 指向原镜号。'
        '需要拆镜时，按剧情顺序返回多条 repair_of 相同的镜头。合格镜头已由服务器保留，禁止重复输出、改写或重新编号。'
        '修正时间、结构或引用时，完整保留出错镜头的全部台词、说话者和顺序；拆分后每镜时间轴从零开始。\n'
    )
    return text + json.dumps({**{key: checkpoint[key] for key in ('accepted_shots', 'pending', 'protocol_errors')},
        'repair_targets': {number: checkpoint['candidates'][number] for number in checkpoint['pending']}}, ensure_ascii=False)


def semantic_repair(language):
    return (
        'Return only corrected shots from repair_targets; set repair_of to the original shot number. '
        'Split shots may repeat repair_of in story order. Other shots are read-only and retained by the server. '
        'Apply the creative findings only within these shots; do not regenerate the chapter.'
        if language == 'en' else
        '只返回 repair_targets 中镜头的修正版，用 repair_of 指向原镜号；拆镜时按剧情顺序重复该 repair_of。'
        '其他镜头只供衔接参考，服务器会原样保留。仅在指定镜头内落实检查意见，不得重新生成整章。'
    )


def review_locations(language):
    return (
        'For storyboard findings, put the exact existing shot sequence numbers requiring edits in shot_sequences. '
        'If an issue cannot be localized to existing shots, return [] and describe it; do not request a full rewrite.'
        if language == 'en' else
        '检查分镜时，用 shot_sequences 列出该问题实际需要修改的已有镜号。'
        '无法定位到已有镜头的全局问题返回 [] 并说明，不要求整章重写。'
    )
