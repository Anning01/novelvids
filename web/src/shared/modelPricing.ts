import type { ImageGenerationModel, ModelPricing } from '@/types'

export function defaultPricing(category: 'llm' | 'image' | 'video' | 'asr', tiers: string[] = []): ModelPricing {
  if (category === 'llm') {
    return { type: 'text', currency: 'CNY', input_price_per_1m: 0, output_price_per_1m: 0 }
  }
  if (category === 'asr') {
    return { type: 'asr', currency: 'CNY', billing_unit: 'minute', price_per_minute: 0 }
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
  inputCount = 0,
  pixels?: number,
): number {
  if (!pricing || pricing.type !== 'image') return 0
  let tier = clarity ?? ''
  if (pricing.billing_unit === 'pixel_tier') {
    if (!pixels) return NaN
    const low = pixels <= 2_610_000
    if ('single_low' in (pricing.prices || {})) tier = low ? 'single_low' : 'single_high'
    else if (pixels <= 4_630_000) tier = low ? 'low' : 'high_capped'
    else return NaN
  }
  const input = pricing.input_image
  const fee = input ? Math.max(0, inputCount - input.first_free) * input.price_per_image : 0
  const unit = pricing.prices?.[tier] ?? (pricing.billing_unit === 'pixel_tier' ? NaN : 0)
  return unit * count + fee
}

export function estimateAssetImageCost(
  model: ImageGenerationModel | null, params: { clarity: string; aspectRatio: string; generationCount: number }, inputs: number,
) {
  const caps = model?.capabilities
  const size = caps?.sizes?.[params.clarity]?.[caps.aspect_ratios.indexOf(params.aspectRatio)]
  const [width, height] = size?.split('x').map(Number) ?? []
  return estimateImageCost(model?.pricing, params.clarity, params.generationCount, inputs, width && height ? width * height : undefined)
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
