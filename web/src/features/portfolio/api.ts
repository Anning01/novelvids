import { API_BASE, request } from '@/api'
import { dateLocale, tr } from '@/i18n'
import type { SingleResponse } from '@/types'
import type { FinishedVersion } from '@/features/finished-episodes/api'

export type WorkStatus = 'private' | 'pending' | 'public' | 'withdrawn'
export type WorkFilter = 'all' | 'pending' | 'public' | 'private' | 'featured'
export type WorkAction = 'submit' | 'approve' | 'publish' | 'withdraw' | 'recommend'

export interface WorkSummary {
  project_id: number
  title: string
  category: string
  tags: string[]
  status: WorkStatus
  featured: boolean
  featured_order: number
  episode_count: number
  duration: number | null
  resolution: string
  cover_export_id: number
  producer: string
  production_seconds?: number | null
  recorded_cost?: number | null
  cost_scope?: 'project' | 'self' | null
  archived_at: string
  updated_at: string
  last_action: string
}

export interface WorkEpisode {
  chapter_id: number
  number: number
  title: string
  version: FinishedVersion
  published_id: number | null
}

export interface WorkDetail extends WorkSummary {
  description: string
  cover_chapter_id: number | null
  revision: number
  episodes: WorkEpisode[]
  can_edit: boolean
  can_manage: boolean
}

export type WorkProfile = Pick<WorkDetail, 'title' | 'description' | 'tags' | 'cover_chapter_id' | 'revision'>
type Option = { id: number; name: string }

interface WorkList {
  items: WorkSummary[]
  total: number
  counts: Record<WorkFilter, number>
  recent: WorkSummary[]
  categories: string[]
  producers: Option[]
  archive_options: Option[]
}

const root = '/portfolio'
export const workApi = {
  list(filters: Record<string, string>, signal?: AbortSignal) {
    return request<SingleResponse<WorkList>>(`${root}?${new URLSearchParams(filters)}`, { signal })
  },
  detail(id: number, publicView: boolean, signal?: AbortSignal) {
    return request<SingleResponse<WorkDetail>>(`${root}${publicView ? '/public' : ''}/${id}`, { signal })
  },
  save(id: number, body: WorkProfile) {
    return request<SingleResponse<WorkDetail>>(`${root}/${id}`, { method: 'PUT', body: JSON.stringify(body) })
  },
  action(id: number, body: { action: WorkAction; revision: number; export_ids?: number[]; featured?: boolean; featured_order?: number }) {
    return request<SingleResponse<WorkDetail>>(`${root}/${id}/status`, { method: 'PUT', body: JSON.stringify(body) })
  },
  publicMedia(id: number, version: number, kind: 'cover' | 'video') {
    return `${API_BASE}${root}/public/${id}/episodes/${version}/${kind}`
  },
}

const statusLabels: Record<WorkStatus, string> = { private: '仅团队可见', pending: '待审核', public: '已公开', withdrawn: '已下架' }
export const workStatus = (status: WorkStatus) => tr(statusLabels[status])
export const workDate = (value: string, full = false) => new Date(value).toLocaleDateString(dateLocale.value, {
  year: full ? 'numeric' : undefined, month: 'short', day: 'numeric',
})
export const workLength = (seconds: number | null) => {
  if (seconds === null) return '—'
  const total = Math.round(seconds)
  if (total < 60) return tr('{p0} 秒', { p0: total })
  const minutes = Math.floor(total / 60)
  return total % 60 ? tr('{p0} 分 {p1} 秒', { p0: minutes, p1: total % 60 }) : tr('{p0} 分钟', { p0: minutes })
}
export const workResolution = (value: string) => value === 'mixed' ? tr('混合分辨率') : value || '—'

export function productionTime(seconds: number | null | undefined): string {
  if (seconds == null) return tr('待确认')
  if (seconds < 3600) return workLength(seconds)
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor(seconds / 3600) % 24
  const minutes = Math.floor(seconds / 60) % 60
  const parts = []
  if (days) parts.push(tr('{p0} 天', { p0: days }))
  if (hours) parts.push(tr('{p0} 小时', { p0: hours }))
  if (minutes && !days) parts.push(tr('{p0} 分钟', { p0: minutes }))
  return parts.join(' ')
}

export function productionCostLabel(scope: WorkSummary['cost_scope']): string {
  return tr(scope === 'self' ? '本人已花费' : '项目已花费')
}
