import type { ModelPricing } from '@/types'

export function defaultPricing(category: 'llm' | 'image' | 'video', tiers: string[] = []): ModelPricing {
  if (category === 'llm') {
    return { type: 'text', currency: 'CNY', input_price_per_1m: 0, output_price_per_1m: 0 }
  }
  const prices: Record<string, number> = {}
  tiers.forEach(tier => { prices[tier] = 0 })
  return { type: category === 'image' ? 'image' : 'video', currency: 'CNY', prices }
}

export function pricingTiers(pricing: ModelPricing | null | undefined): string[] {
  return pricing?.prices ? Object.keys(pricing.prices) : []
}

export function estimateImageCost(
  pricing: ModelPricing | null | undefined,
  clarity: string | null | undefined,
  count = 1,
): number {
  if (!pricing || pricing.type !== 'image') return 0
  const unit = pricing.prices?.[clarity ?? ''] ?? 0
  return Number(unit || 0) * Math.max(1, Number(count) || 1)
}

export function pricingDiscount(pricing: ModelPricing | null | undefined): number {
  const value = Number(pricing?.discount)
  return value > 0 ? value : 1
}

export function pricingDiscountDescription(pricing: ModelPricing | null | undefined): string {
  return pricing?.discount_description || ''
}

const VIDEO_TOKENS_PER_SECOND: Record<string, number> = {
  '480p': 10044,
  '720p': 21600,
  '1080p': 48600,
  '4k': 194400,
}

export function estimateVideoCost(
  pricing: ModelPricing | null | undefined,
  resolution: string | null | undefined,
  durationSeconds = 0,
  hasVideoReference = false,
  inputVideoSeconds = 0,
  inputImageCount = 0,
): number {
  if (!pricing || pricing.type !== 'video') return 0
  const resolutionKey = resolution ?? ''
  const outputPrice = pricing.prices?.[resolutionKey] ?? 0
  const referencePrice = pricing.video_reference_prices?.[resolutionKey] ?? outputPrice
  const imageFee = pricing.input_image
    ? Math.max(0, Number(inputImageCount || 0) - pricing.input_image.first_free) * pricing.input_image.price_per_image
    : 0
  if (pricing.billing_unit === 'second') {
    const outputCost = Number(outputPrice || 0) * Number(durationSeconds || 0)
    const inputVideoCost = hasVideoReference
      ? Number(referencePrice || 0) * Number(inputVideoSeconds || 0)
      : 0
    return outputCost + inputVideoCost + imageFee
  }
  const table = hasVideoReference ? (pricing.video_reference_prices || pricing.prices) : pricing.prices
  const tokenPrice = table?.[resolutionKey] ?? 0
  const tokensPerSecond = VIDEO_TOKENS_PER_SECOND[resolutionKey] ?? 0
  const tokens = tokensPerSecond * (Number(durationSeconds || 0) + Number(inputVideoSeconds || 0))
  return Number(tokenPrice || 0) * tokens / 1_000_000 + imageFee
}
