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
