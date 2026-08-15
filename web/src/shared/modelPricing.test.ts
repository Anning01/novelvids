import { describe, expect, it } from 'vitest'
import { defaultPricing, pricingTiers } from './modelPricing'

describe('modelPricing', () => {
  it('文本模型默认定价结构', () => {
    expect(defaultPricing('llm')).toEqual({
      type: 'text', currency: 'CNY', input_price_per_1m: 0, output_price_per_1m: 0,
    })
  })
  it('图片模型按档位生成价格对象', () => {
    expect(defaultPricing('image', ['1K', '2K']).prices).toEqual({ '1K': 0, '2K': 0 })
  })
  it('pricingTiers 提取档位列表', () => {
    expect(pricingTiers({ type: 'image', currency: 'CNY', prices: { '1K': 0.1 } })).toEqual(['1K'])
    expect(pricingTiers(null)).toEqual([])
  })
})
