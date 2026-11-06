import { API_BASE, request } from '@/api'
import type { SingleResponse } from '@/types'

export interface FinishedVersion {
  id: number
  revision: number | null
  completed_at: string
  duration: number | null
  width: number | null
  height: number | null
  fps: number | null
}
const root = '/finished-episodes'
export const finishedApi = {
  versions: (chapter: number) => request<SingleResponse<FinishedVersion[]>>(`${root}/chapters/${chapter}/versions`),
  coverUrl: (id: number, token?: string | null) => `${API_BASE}${root}/versions/${id}/cover${token ? `?token=${encodeURIComponent(token)}` : ''}`,
  videoUrl: (id: number, download = false, token?: string | null) => {
    const params = new URLSearchParams()
    if (download) params.set('download', 'true')
    if (token) params.set('token', token)
    const qs = params.toString()
    return `${API_BASE}${root}/versions/${id}/video${qs ? `?${qs}` : ''}`
  },
}
export function versionName(version: FinishedVersion): string {
  return `v${version.revision ?? version.id}`
}
export function runtime(seconds: number | null): string {
  if (seconds === null) return '—'
  const total = Math.round(seconds)
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}
