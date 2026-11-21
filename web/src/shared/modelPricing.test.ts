import { describe, expect, it } from 'vitest'
import type { ImageGenerationModel, ModelPricing } from '@/types'
import { defaultPricing, estimateAssetImageCost, estimateImageCost, estimateVideoCost, pricingDiscount, pricingDiscountDescription, pricingTiers } from './modelPricing'

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

it('quotes single-image pixel tiers and charges reference images per request', () => {
  const pricing: ModelPricing = { type: 'image', currency: 'CNY', billing_unit: 'pixel_tier',
    prices: { low: 0.13, high_capped: 0.23 }, input_image: { first_free: 0, price_per_image: 0.05 } }
  expect(estimateImageCost(pricing, '2K', 1, 2, 2610000)).toBeCloseTo(0.23)
  expect(estimateImageCost(pricing, '2K', 1, 2, 2611000)).toBeCloseTo(0.33)
})

it('distinguishes a configured zero-cost asset tier from missing or incomplete pricing', () => {
  const params = { clarity: '2K', aspectRatio: '1:1', generationCount: 1 }
  const model: ImageGenerationModel = {
    config_id: 1, name: '测试模型', model: 'test', model_type: 'gpt_image_2', concurrency: 1,
    capabilities: {
      aspect_ratios: ['1:1'], clarities: ['2K'], output_formats: ['png'], generation_counts: [1],
      default_aspect_ratio: '1:1', default_clarity: '2K', default_output_format: 'png', default_generation_count: 1,
    },
    pricing: { type: 'image', currency: 'CNY', prices: { '2K': 0 } },
  }
  expect(estimateAssetImageCost(model, params, 0)).toBe(0)
  expect(estimateAssetImageCost(null, params, 0)).toBeNaN()
  expect(estimateAssetImageCost(model, { ...params, clarity: '4K' }, 0)).toBeNaN()
  expect(estimateAssetImageCost({ ...model, pricing: {type: 'image', currency: 'CNY', billing_unit: 'pixel_tier', prices: {low: .13}} }, params, 0)).toBeNaN()
})
