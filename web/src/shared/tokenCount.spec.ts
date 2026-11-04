import { expect, it } from 'vitest'
import { formatTokenCount } from './tokenCount'

it.each([
  [0, '0'], [999, '999'], [1000, '1K'], [5368, '5K'], [438265, '438K'],
  [310920, '311K'], [127345, '127K'], [999999, '1M'], [2000000, '2M'],
  [NaN, '0'], [Infinity, '0'], [-1, '0'],
])('formats %s tokens as %s without decimal places', (value, expected) => {
  expect(formatTokenCount(value)).toBe(expected)
})

it('retains existing billing precision when requested', () => {
  expect(formatTokenCount(438265, 1)).toBe('438.3K')
  expect(formatTokenCount(1200000, 1)).toBe('1.2M')
})
