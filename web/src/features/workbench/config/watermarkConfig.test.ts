import { describe, expect, it } from 'vitest'
import {
  WATERMARK_PRESETS,
  normalizeWatermarkConfig,
  watermarkPresetConfig,
} from './watermarkConfig'

describe('watermarkConfig', () => {
  it.each([
    ['top-left', { x: 0.14, y: 0.14 }],
    ['top-right', { x: 0.86, y: 0.14 }],
    ['bottom-left', { x: 0.14, y: 0.86 }],
    ['bottom-right', { x: 0.86, y: 0.86 }],
    ['center', { x: 0.5, y: 0.5 }],
  ] as const)('maps %s to the reference coordinates', (preset, expected) => {
    expect(watermarkPresetConfig(preset)).toMatchObject({ ...expected, scale: 0.2 })
  })

  it('exposes the same five presets and Chinese labels as the reference', () => {
    expect(WATERMARK_PRESETS.map(item => [item.value, item.label])).toEqual([
      ['top-left', '左上角'],
      ['top-right', '右上角'],
      ['bottom-left', '左下角'],
      ['bottom-right', '右下角'],
      ['center', '居中'],
    ])
  })

  it('clamps custom positions and scale to the reference slider ranges', () => {
    expect(normalizeWatermarkConfig({
      resourceUrl: '/media/logo.png',
      x: -1,
      y: 4,
      scale: 2,
    })).toEqual({
      resourceUrl: '/media/logo.png',
      x: 0,
      y: 1,
      scale: 1,
    })

    expect(normalizeWatermarkConfig({
      resourceUrl: '',
      x: Number.NaN,
      y: Number.NaN,
      scale: 0,
    })).toEqual({
      resourceUrl: '',
      x: 0.86,
      y: 0.86,
      scale: 0.05,
    })
  })
})
