
import { tr } from '@/i18n'
import type { BillingRecord } from '@/types'
import { statusLabel } from '@/api'

export function money(value: number, currency = 'CNY'): string {
  const symbol = currency === 'CNY' ? '¥' : currency === 'USD' ? '$' : `${currency} `
  if (!value) return `${symbol}0`
  const abs = Math.abs(value)
  return `${symbol}${value.toFixed(abs >= 1 ? 2 : abs >= 0.01 ? 4 : 6)}`
}

export function formatTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`
  return String(value)
}

export function usageLabel(item: BillingRecord): string {
  const usage = item.usage || {}
  const num = (value: unknown) => Number(value) || 0
  if (item.billing_type === 'text') return tr('输入 {p0} · 输出 {p1} token', { p0: formatTokens(num(usage.input_tokens)), p1: formatTokens(num(usage.output_tokens)) })
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
  return ({ get team_key() { return tr('团队 Key') }, get balance() { return tr('团队余额') }, get mixed() { return tr('混合来源') } })[source || ''] || tr('平台')
}

export function recordStatus(item: BillingRecord): string {
  if (item.record_kind === 'agent_conversation') {
    if (item.statuses?.some(status => [1, 2, 6].includes(status))) return tr('处理中')
    if (item.statuses?.includes(4)) return tr('含失败记录')
    if (item.statuses?.includes(5)) return tr('含取消记录')
  }
  return statusLabel(item.status)
}
