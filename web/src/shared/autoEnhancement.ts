import type { AutoEnhancement, ModelPricing, Video } from '@/types'
import { tr } from '@/i18n'
import type { EnhancementModel } from '@/features/video-export/api'

export function resolutionShortSide(value: string): number {
  const normalized = value.toLowerCase()
  return ({ '2k': 1440, '4k': 2160 } as Record<string, number>)[normalized] || Number.parseInt(normalized) || 0
}

export function autoEnhancementAvailable(value: AutoEnhancement | null | undefined, models: EnhancementModel[], resolution: string) {
  return !value || models.some(model => model.id === value.model_config_id
    && model.resolutions.some(target => target.value === value.resolution && target.short_side > resolutionShortSide(resolution)))
}

export function currentAutoEnhancement(value: AutoEnhancement | null | undefined, models: EnhancementModel[]): AutoEnhancement | null {
  if (!value) return null
  const version = models.find(item => item.id === value.model_config_id)?.config_version
  return { ...value, ...(version ? { config_version: version } : {}) }
}

export function readAutoEnhancement(value: unknown): AutoEnhancement | null {
  if (!value || typeof value !== 'object') return null
  const data = value as Record<string, unknown>
  if (!Number.isInteger(data.model_config_id) || Number(data.model_config_id) < 1 || !['720p', '1080p', '2k', '4k'].includes(String(data.resolution))) return null
  return { model_config_id: Number(data.model_config_id), resolution: data.resolution as AutoEnhancement['resolution'],
    ...(typeof data.config_version === 'string' ? { config_version: data.config_version } : {}) }
}

export function isVideoGenerationActive(video: Pick<Video, 'status' | 'metadata'>): boolean {
  if ([1, 2, 6].includes(video.status)) return true
  const followup = video.metadata?.auto_enhancement as { stage?: string } | undefined
  return video.status === 3 && Boolean(followup && ['waiting_video', 'preparing', 'enhancing'].includes(followup.stage || ''))
}

export function autoEnhancementLabel(video: Video | null | undefined): string {
  const state = video?.metadata?.auto_enhancement as { stage?: string } | undefined
  return ({ waiting_video: tr('生成成功后将自动高清化'), preparing: tr('正在准备自动高清化'), enhancing: tr('正在自动高清化'),
    completed: tr('自动高清化已完成'), failed: tr('自动高清化未完成，原视频已保留'),
    needs_review: tr('高清化提交结果待核对，请勿重复提交'), needs_confirmation: tr('增强配置已变化，请重新确认高清化'),
    skipped: tr('目标清晰度不高于原视频，已跳过增强'), cancelled: tr('自动高清化已停止') } as Record<string, string>)[state?.stage || ''] || ''
}

export function preserveAutoEnhancement(previous: Video | undefined, current: Video): Video {
  const before = previous?.metadata?.auto_enhancement as { stage?: string } | undefined
  const after = current.metadata?.auto_enhancement as { stage?: string } | undefined
  if (before && ['completed', 'failed', 'needs_review', 'needs_confirmation', 'skipped', 'cancelled'].includes(before.stage || '')
    && after && ['waiting_video', 'preparing', 'enhancing'].includes(after.stage || '')) {
    return { ...current, metadata: { ...current.metadata, auto_enhancement: before } }
  }
  return current
}

export function enhancementEstimate(pricing: ModelPricing | null | undefined, shortSide: number, seconds: number) {
  const tiers = (pricing?.tiers || []).filter(tier => tier.short_side_max >= shortSide)
  const smallest = Math.min(...tiers.map(tier => tier.short_side_max))
  const costs = tiers.filter(tier => tier.short_side_max === smallest).map(tier => tier.price * seconds / 60 * (pricing?.discount ?? 1))
  return costs.length ? { min: Math.min(...costs), max: Math.max(...costs) } : null
}
