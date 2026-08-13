import { describe, expect, it } from 'vitest'
import { balanceMediaGalleryRows, containedAspectRatioSize, mediaAspectRatioCss, parseMediaAspectRatio } from './mediaAspectRatio'

describe('media aspect ratio helpers', () => {
  it('accepts provider and pixel ratio formats', () => {
    expect(parseMediaAspectRatio('9:16')).toEqual([9, 16])
    expect(parseMediaAspectRatio('1424x800')).toEqual([1424, 800])
    expect(mediaAspectRatioCss('4/3')).toBe('4 / 3')
  })

  it('contains mixed-ratio stack layers without stretching them', () => {
    expect(containedAspectRatioSize('16:9', '9:16')).toEqual({ width: '100%', height: '31.640625%' })
    expect(containedAspectRatioSize('9:16', '16:9')).toEqual({ width: '31.640625%', height: '100%' })
  })

  it('balances ordered mixed-ratio galleries into bounded rows', () => {
    const items = [
      { id: 1, ratio: '16:9' },
      { id: 2, ratio: '9:16' },
      { id: 3, ratio: '1:1' },
      { id: 4, ratio: '16:9' },
      { id: 5, ratio: '9:16' },
    ]
    const rows = balanceMediaGalleryRows(items, item => item.ratio, { targetRowWidth: 1280 })

    expect(rows.flat().map(item => item.id)).toEqual([1, 2, 3, 4, 5])
    expect(rows.length).toBeLessThan(items.length)
    expect(rows.every(row => row.length <= 4)).toBe(true)
  })
})
