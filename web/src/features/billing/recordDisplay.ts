
import { tr } from '@/i18n'
import type { BillingRecord } from '@/types'
import { statusLabel } from '@/api'
import { formatTokenCount } from '@/shared/tokenCount'

export function money(value: number, currency = 'CNY'): string {
  const symbol = currency === 'CNY' ? '¥' : currency === 'USD' ? '$' : `${currency} `
  if (!value) return `${symbol}0`
  const abs = Math.abs(value)
  return `${symbol}${value.toFixed(abs >= 1 ? 2 : abs >= 0.01 ? 4 : 6)}`
}

export function recordCost(item: BillingRecord): string {
  if (item.settlement_status === 'pending') return tr('待结算')
  if (item.settlement_status === 'review') return tr('待结算')
  return money(item.cost, item.currency)
}

export function formatTokens(value: number): string {
  return formatTokenCount(value, 1)
}

export function usageLabel(item: { billing_type: string; usage: Record<string, unknown>; duration_seconds?: number | null }): string {
  const usage = item.usage || {}
  const num = (value: unknown) => Number(value) || 0
  if (item.billing_type === 'text') return tr('输入 {p0} · 输出 {p1} token', { p0: formatTokens(num(usage.input_tokens)), p1: formatTokens(num(usage.output_tokens)) })
  if (item.billing_type === 'asr') {
    const duration = usage.duration_seconds ?? item.duration_seconds
    const seconds = Number(duration)
    return duration != null && Number.isFinite(seconds) && seconds >= 0
      ? tr('{p0} 秒', { p0: seconds })
      : '—'
  }
  if (item.billing_type === 'media_processing') {
    return usage.missing_usage ? tr('用量正在同步') : tr('{p0}s · {p1} · {p2}fps', { p0: num(usage.seconds), p1: String(usage.resolution || '—'), p2: num(usage.fps) })
  }
  if (item.billing_type === 'image') {
    const count = num(usage.image_count)
    const clarity = usage.clarity ? ` @${usage.clarity}` : ''
    const input = num(usage.input_image_count)
    return tr('{p0} 张{p1}{p2}', { p0: count, p1: clarity, p2: input ? ` · 输入 ${input} 张` : '' })
  }
  const seconds = num(usage.seconds)
  const resolution = usage.resolution ? ` @${usage.resolution}` : ''
  const input = num(usage.input_video_seconds)
  const inputImages = num(usage.input_image_count)
  return tr('{p0}s{p1}{p2}{p3}', { p0: seconds, p1: resolution, p2: input ? ` · 参考视频 ${input}s` : '', p3: inputImages ? ` · 输入图片 ${inputImages} 张` : '' })
}

export function costSourceLabel(source?: string): string {
  return ({ get platform_key() { return tr('平台 Key') }, get team_key() { return tr('团队 Key') }, get balance() { return tr('团队余额') }, get mixed() { return tr('混合来源') } })[source || ''] || tr('平台')
}

export function recordStatus(item: BillingRecord): string {
  if (item.billing_type === 'media_processing' && (item.usage?.missing_usage || item.usage?.accounting_needs_review)) return tr('费用待结算')
  if (item.record_kind === 'agent_conversation') {
    if (item.statuses?.some(status => [1, 2, 6].includes(status))) return tr('处理中')
    if (item.statuses?.includes(4)) return tr('含失败记录')
    if (item.statuses?.includes(5)) return tr('含取消记录')
  }
  return statusLabel(item.status)
}

export function recordStatusHint(item: BillingRecord): string | undefined {
  return item.record_kind === 'agent_conversation' && item.statuses?.includes(4)
    ? tr('该会话有部分步骤未完成，不代表所有调用失败。展开记录可查看各次状态和实际用量。') : undefined
}
