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
  if (item.billing_type === 'text') return `输入 ${formatTokens(num(usage.input_tokens))} · 输出 ${formatTokens(num(usage.output_tokens))} token`
  if (item.billing_type === 'image') {
    const count = num(usage.image_count)
    const clarity = usage.clarity ? ` @${usage.clarity}` : ''
    const input = num(usage.input_image_count)
    return `${count} 张${clarity}${input ? ` · 输入 ${input} 张` : ''}`
  }
  const seconds = num(usage.seconds)
  const resolution = usage.resolution ? ` @${usage.resolution}` : ''
  const input = num(usage.input_video_seconds)
  const inputImages = num(usage.input_image_count)
  return `${seconds}s${resolution}${input ? ` · 参考视频 ${input}s` : ''}${inputImages ? ` · 输入图片 ${inputImages} 张` : ''}`
}

export function costSourceLabel(source?: string): string {
  return ({ team_key: '团队 Key', balance: '团队余额', mixed: '混合来源' })[source || ''] || '平台'
}

export function recordStatus(item: BillingRecord): string {
  if (item.record_kind === 'agent_conversation') {
    if (item.statuses?.some(status => [1, 2, 6].includes(status))) return '处理中'
    if (item.statuses?.includes(4)) return '含失败记录'
    if (item.statuses?.includes(5)) return '含取消记录'
  }
  return statusLabel(item.status)
}
