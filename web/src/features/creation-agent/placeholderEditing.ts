export interface TextSelection { start: number; end: number }
export interface PlaceholderRange extends TextSelection { value: string }

export function placeholderRanges(text: string): PlaceholderRange[] {
  return [...text.matchAll(/\{\{\s*[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*\s*\}\}/g)]
    .map(match => ({ start: match.index, end: match.index + match[0].length, value: match[0] }))
}

export function atomicSelection(text: string, start: number, end: number): TextSelection {
  for (const token of placeholderRanges(text)) {
    if (start === end && start > token.start && start < token.end) {
      const edge = start - token.start < token.end - start ? token.start : token.end
      return { start: edge, end: edge }
    }
    if (start < end && start < token.end && end > token.start) {
      start = Math.min(start, token.start)
      end = Math.max(end, token.end)
    }
  }
  return { start, end }
}

export function splitsPlaceholder(before: string, after: string, selection?: TextSelection): boolean {
  if (before === after) return false
  if (selection) {
    const afterEnd = after.length - (before.length - selection.end)
    if (afterEnd >= selection.start && before.slice(0, selection.start) === after.slice(0, selection.start)
      && before.slice(selection.end) === after.slice(afterEnd)) {
      return placeholderRanges(before).some(token =>
        (selection.start > token.start && selection.start < token.end) || (selection.end > token.start && selection.end < token.end))
    }
  }
  let start = 0
  while (start < before.length && start < after.length && before[start] === after[start]) start++
  let end = before.length
  let afterEnd = after.length
  while (end > start && afterEnd > start && before[end - 1] === after[afterEnd - 1]) { end--; afterEnd-- }
  return placeholderRanges(before).some(token => {
    return (start > token.start && start < token.end) || (end > token.start && end < token.end)
  })
}
