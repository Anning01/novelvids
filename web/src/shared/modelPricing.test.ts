import { describe, expect, it } from 'vitest'
import type { ModelPricing } from '@/types'
import { defaultPricing, estimateImageCost, estimateVideoCost, pricingDiscount, pricingDiscountDescription, pricingTiers } from './modelPricing'

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
  it('estimateImageCost 按清晰度与张数估算', () => {
    const pricing: ModelPricing = { type: 'image', currency: 'CNY', prices: { '1K': 0.3, '2K': 0.6 } }
    expect(estimateImageCost(pricing, '1K', 1)).toBe(0.3)
    expect(estimateImageCost(pricing, '2K', 2)).toBe(1.2)
    expect(estimateImageCost(pricing, '3K', 1)).toBe(0)
    expect(estimateImageCost(null, '1K', 1)).toBe(0)
  })
  it('pricingDiscount 默认 1，读取折扣倍数', () => {
    expect(pricingDiscount(null)).toBe(1)
    expect(pricingDiscount({ type: 'image', currency: 'CNY', prices: {} })).toBe(1)
    expect(pricingDiscount({ type: 'image', currency: 'CNY', prices: {}, discount: 0.9 })).toBe(0.9)
    expect(pricingDiscount({ type: 'image', currency: 'CNY', prices: {}, discount: 1.5 })).toBe(1.5)
    expect(pricingDiscount({ type: 'image', currency: 'CNY', prices: {}, discount: 0 })).toBe(1)
  })
  it('pricingDiscountDescription 读取描述', () => {
    expect(pricingDiscountDescription(null)).toBe('')
    expect(pricingDiscountDescription({ type: 'image', currency: 'CNY', prices: {}, discount_description: '限时9折' })).toBe('限时9折')
  })
  it('MiniMax H3 按生成秒数、输入视频秒数和超额图片估算', () => {
    const pricing: ModelPricing = {
      type: 'video',
      currency: 'CNY',
      billing_unit: 'second',
      prices: { '768P': 0.5, '2K': 0.8 },
      video_reference_prices: { '768P': 0.5, '2K': 0.8 },
      input_image: { first_free: 5, price_per_image: 0.2 },
    }
    expect(estimateVideoCost(pricing, '768P', 5)).toBe(2.5)
    expect(estimateVideoCost(pricing, '768P', 5, true, 3, 7)).toBe(4.4)
    expect(estimateVideoCost(pricing, '2K', 5)).toBe(4)
  })
})
