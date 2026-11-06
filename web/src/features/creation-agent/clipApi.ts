import { request } from '@/api'
import type { SingleResponse, VideoReferenceMedia } from '@/types'
import type { AgentRun } from './types'

export interface ClipInput {
  request_id: string
  task_type: 'video' | 'image'
  mode: 'direct' | 'agent' | 'reference'
  model_config_id: number
  prompt: string
  aspect_ratio: string
  resolution: string
  duration: number
  reference_media: VideoReferenceMedia[]
  reference_binding?: 'all' | 'mentions'
}
export interface ClipSummary { project_id: number; name: string; aspect_ratio: string; created_at: string }
export interface ClipSession extends ClipInput, ClipSummary {
  chapter_id: number
  scene_id: number | null
  asset_id: number | null
  conversation_id: number
  model_name: string
  assistant_model_config_id: number
  image_model_config_id: number | null
}
export interface ClipQuote {
  estimated_cost: string | null
  original_cost?: string | null
  discount?: string | null
  discount_description?: string | null
  available_balance: string | null
  shortfall: string | null
  currency: string
  allowed: boolean
  reason: string
  note: string
}
export const clipApi = {
  quote: (input: Omit<ClipInput, 'request_id'>, signal?: AbortSignal) => request<SingleResponse<ClipQuote>>('/experience/quote', {method:'POST', body:JSON.stringify(input), signal}),
  create: (input: ClipInput) => request<SingleResponse<ClipSession>>('/experience/generate', { method: 'POST', body: JSON.stringify(input) }),
  recent: () => request<SingleResponse<ClipSummary[]>>('/experience/sessions'),
  session: (id: number) => request<SingleResponse<ClipSession>>(`/experience/sessions/${id}`),
  start: (id: number) => request<SingleResponse<AgentRun>>(`/experience/sessions/${id}/start`, { method: 'POST' }),
}
