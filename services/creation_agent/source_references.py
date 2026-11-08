"""Resolve model selections to server-owned source text, never generated prose."""

import re

from utils.messages import localized_message

MIN_BOUNDARY_CHARACTERS = 24


def source_paragraphs(text: str, offset: int = 0) -> list[dict]:
    paragraphs = []
    position = offset
    for line in text.splitlines(keepends=True):
        if line.strip():
            paragraphs.append({'id': len(paragraphs) + 1, 'start': position,
                'end': position + len(line), 'text': line})
        position += len(line)
    return paragraphs


def compact_with_positions(text):
    positions = [index for index, char in enumerate(text) if not char.isspace()]
    return ''.join(text[index] for index in positions), positions


def unique_position(text, needle):
    position = text.find(needle)
    return position if needle and position >= 0 and text.find(needle, position + 1) < 0 else None


def legacy_quote_span(text, quote):
    position = unique_position(text, quote)
    if position is not None:
        return position, position + len(quote)
    compact, positions = compact_with_positions(text)
    quoted = re.sub(r'\s+', '', quote)
    position = unique_position(compact, quoted)
    if position is not None:
        return positions[position], positions[position + len(quoted) - 1] + 1
    # Old receipts contain model-copied quotations. Two exact, unique boundary
    # anchors can identify their original span even if the copied middle is wrong.
    # The recovered text is always sliced from the source; no fuzzy text is saved.
    if len(quoted) >= 2 * MIN_BOUNDARY_CHARACTERS:
        first = unique_position(compact, quoted[:MIN_BOUNDARY_CHARACTERS])
        last = unique_position(compact, quoted[-MIN_BOUNDARY_CHARACTERS:])
        if first is not None and last is not None and first + MIN_BOUNDARY_CHARACTERS <= last:
            return positions[first], positions[last + MIN_BOUNDARY_CHARACTERS - 1] + 1
    raise ValueError(localized_message('无法唯一定位引用，请选择当前页给出的段落编号'))


def resolve_reading(reading, facts, *, require_paragraphs=False):
    text, offset, end = facts['content'], facts['start'], facts['end']
    paragraphs = {row['id']: row for row in source_paragraphs(text, offset)}
    if require_paragraphs and paragraphs and not reading.candidates:
        raise ValueError(localized_message('请至少选择一个体现本页剧情的段落作为候选'))
    resolved = []
    for selection in reading.candidates:
        if selection.chapter_id != facts['chapter_id']:
            raise ValueError(localized_message('阅读结果引用了当前片段之外的原文'))
        if selection.first_paragraph is not None:
            first = paragraphs.get(selection.first_paragraph)
            last = paragraphs.get(selection.last_paragraph or selection.first_paragraph)
            if not first or not last or first['start'] > last['start']:
                raise ValueError(localized_message('段落编号不存在或顺序错误，请使用当前页给出的编号'))
            start, stop = first['start'], last['end']
        elif require_paragraphs:
            raise ValueError(localized_message('请使用 first_paragraph 和 last_paragraph 选择原文，不要计算字符位置或抄写引文'))
        elif selection.quote:
            if offset <= selection.start < selection.end <= end and text[selection.start - offset:selection.end - offset] == selection.quote:
                start, stop = selection.start, selection.end
            else:
                start, stop = legacy_quote_span(text, selection.quote)
                start, stop = start + offset, stop + offset
        else:
            start, stop = selection.start, selection.end
        if not offset <= start < stop <= end:
            raise ValueError(localized_message('阅读结果引用了当前片段之外的原文'))
        original = text[start - offset:stop - offset]
        resolved.append(selection.model_copy(update={'start': start, 'end': stop,
            'quote': original if len(original) <= 8000 else None,
            'reference_id': f'{selection.chapter_id}:{start}:{stop}'}))
    return reading.model_copy(update={'candidates': resolved})


def resolve_plan_references(selections, chapters, *, strict=False):
    references = {}
    legacy = {}
    for chapter in chapters:
        for page in chapter.pages:
            for candidate in page.candidates:
                key = candidate.reference_id or f'{candidate.chapter_id}:{candidate.start}:{candidate.end}'
                references[key] = candidate
                legacy[(candidate.chapter_id, candidate.start, candidate.end)] = candidate
    for selection in selections:
        if selection.reference_id:
            candidate = references.get(selection.reference_id)
            if candidate is None or candidate.chapter_id != selection.chapter_id:
                raise ValueError(localized_message('引用编号不在已读取的候选中，请复制对应的 reference_id'))
        else:
            candidate = legacy.get((selection.chapter_id, selection.start, selection.end))
            if candidate is None:
                if strict:
                    raise ValueError(localized_message('请使用已读取候选的 reference_id，不要猜测原文位置'))
                # Historical drafts can use any verified span from a read chapter;
                # their version/range/quote are still checked by the source loader.
                continue
        selection.start, selection.end = candidate.start, candidate.end
        selection.quote = candidate.quote
        selection.reference_id = candidate.reference_id
