import { expect, it } from 'vitest'
import { atomicSelection, placeholderRanges, splitsPlaceholder } from './placeholderEditing'

it('treats complete placeholders as single selections including Unicode offsets', () => {
  const text = '你好🙂{{input}}，{{ max_seconds }}'
  const [first, second] = placeholderRanges(text)
  expect(first).toEqual({ start: 4, end: 13, value: '{{input}}' })
  expect(atomicSelection(text, 6, 6)).toEqual({ start: 4, end: 4 })
  expect(atomicSelection(text, 11, 11)).toEqual({ start: 13, end: 13 })
  expect(atomicSelection(text, 6, second!.start + 4)).toEqual({ start: first!.start, end: second!.end })
})

it('permits surrounding prose, whole omission, and formatting without changing variable names', () => {
  const text = '参考 {{max_seconds}} 秒'
  expect(splitsPlaceholder(text, `正文\n${text}`)).toBe(false)
  expect(splitsPlaceholder(text, '参考  秒')).toBe(false)
  expect(splitsPlaceholder(text, '参考 **{{max_seconds}}** 秒')).toBe(false)
  expect(splitsPlaceholder(text, '普通文字，不使用变量')).toBe(false)
  expect(splitsPlaceholder('{{input}}{{input}}', '{{input}}')).toBe(false)
})

it.each(['参考 {{max_second}} 秒', '参考 {{max_seconds} 秒', '参考 {{new_name}} 秒', '参考 {{max_你好seconds}} 秒'])('rejects partial token mutation: %s', after => {
  expect(splitsPlaceholder('参考 {{max_seconds}} 秒', after)).toBe(true)
})

it('permits replacing an explicitly selected whole token even when braces match', () => {
  expect(splitsPlaceholder('{{input}}', '{{language}}', { start: 0, end: 9 })).toBe(false)
})

it('deletes one adjacent variable without confusing its shared braces with the next variable', () => {
  expect(splitsPlaceholder('{{input}}{{language}}', '{{language}}', { start: 0, end: 9 })).toBe(false)
  expect(splitsPlaceholder('{{language}}', '{{input}}{{language}}', { start: 0, end: 0 })).toBe(false)
})
