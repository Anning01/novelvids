import { dateLocale, tr } from '@/i18n'
import { readShortDramaSettings } from '@/shared/shortDramaProject'
import type { Novel } from '@/types'

export function projectKind(project: Novel) {
  if (project.workflow_kind === 'remake') return 'remake'
  return readShortDramaSettings(project).mode ?? 'script'
}

export function projectKindLabel(project: Novel) {
  return { agent: tr('AI 创作'), manual: tr('手动创作'), remake: tr('视频重制'), script: tr('小说 / 剧本') }[projectKind(project)]
}

export function projectNumber(value: number): string {
  return new Intl.NumberFormat(dateLocale.value).format(value)
}

export function projectRuntime(seconds: number, unknownCount = 0) {
  const incomplete = unknownCount > 0
  if (!seconds && incomplete) return { value: tr('待确认'), unit: '', incomplete }
  const useSeconds = seconds > 0 && seconds < 60
  const value = new Intl.NumberFormat(dateLocale.value, { maximumFractionDigits: 1 }).format(useSeconds ? seconds : seconds / 60)
  return { value: `${incomplete ? '≥ ' : ''}${value}`, unit: useSeconds ? tr('秒') : tr('分钟'), incomplete }
}

export function projectDate(value: string) {
  const date = new Date(value.replace(' ', 'T'))
  return Number.isNaN(date.getTime()) ? '' : new Intl.DateTimeFormat(dateLocale.value, { month: 'short', day: 'numeric' }).format(date)
}
