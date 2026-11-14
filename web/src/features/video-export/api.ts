import { request, resetGenerationRequest } from '@/api'
import type { Video, ModelPricing } from '@/types'

export interface ExportProbe { duration: string | number; width: number; height: number; fps: string | number }
export interface ChapterExport {
  id: number; chapter_id: number; parent_export_id: number | null; source_version: string
  source_sha256: string | null; source_probe: Partial<ExportProbe>; output_probe: Partial<ExportProbe>
  source_url: string | null; url: string | null; task_id: string | null; status: number | null
  stage: string | null; error: string | null; created_at: string; recipe: Record<string, unknown>
  selection_current?: boolean
  source_video_id?: number | null
  result_video_id?: number | null
  applied_to_scene?: boolean
}
export interface ExportQuote { amount: string; currency: string; source_sha256: string; quote_version: string; reused_export_id?: number | null }
export interface ExportTask { export_id: number; task_id: string; status: number }
export interface EnhancementModel {
  config_version?: string
  pricing?: ModelPricing | null
  id: number; name: string; input_short_side_max?: number
  resolutions: Array<{ value: string; short_side: number }>
  supported_resolutions?: Array<{ value: string; short_side: number }>
}
interface Response<T> { data: T }

export const exportApi = {
  list: (chapter: number) => request<Response<ChapterExport[]>>(`/video/exports?chapter_id=${chapter}`),
  listVideo: (videoId: number) => request<Response<ChapterExport[]>>(`/video/exports/video/${videoId}`),
  prepareVideo: (videoId: number) => request<Response<ExportTask>>(`/video/exports/video/${videoId}`, { method: 'POST' }),
  models: () => request<Response<EnhancementModel[]>>('/video/exports/models'),
  get: (id: number) => request<Response<ChapterExport>>(`/video/exports/${id}`),
  apply: (id: number) => request<Response<Video>>(`/video/exports/${id}/apply`, { method: 'POST' }),
  prepare: (chapter_id: number) => request<Response<ExportTask>>('/video/exports', { method: 'POST', body: JSON.stringify({ chapter_id }) }),
  quote: (id: number, model: number, resolution = '1080p') => request<Response<ExportQuote>>(`/video/exports/${id}/quote?model_config_id=${model}&resolution=${encodeURIComponent(resolution)}`),
  enhance: async (id: number, model: number, quote: ExportQuote, resolution = '1080p', restart = false) => {
    const url = `/video/exports/${id}/enhance`
    const body = JSON.stringify({ model_config_id: model, source_sha256: quote.source_sha256, quote_version: quote.quote_version, resolution })
    if (restart) await resetGenerationRequest(url, body)
    return request<Response<ExportTask>>(url, { method: 'POST', body })
  },
}
