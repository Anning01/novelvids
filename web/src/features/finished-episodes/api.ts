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
  coverUrl: (id: number) => `${API_BASE}${root}/versions/${id}/cover`,
  videoUrl: (id: number, download = false) => `${API_BASE}${root}/versions/${id}/video${download ? '?download=true' : ''}`,
}
export function versionName(version: FinishedVersion): string {
  return `v${version.revision ?? version.id}`
}
export function runtime(seconds: number | null): string {
  if (seconds === null) return '—'
  const total = Math.round(seconds)
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}
