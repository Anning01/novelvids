import { API_BASE, authHeaders, request, uploadWithProgress } from '@/api'
import type { SingleResponse } from '@/types'
import type { ClipKind, EditDocument, EditorCapabilities, EditorDraft, EditorExport, EditorMedia } from './types'

const root = '/video-editor'
export const editorApi = {
  capabilities: () => request<SingleResponse<EditorCapabilities>>(`${root}/capabilities`),
  get: (chapterId: number, signal?: AbortSignal) => request<SingleResponse<EditorDraft>>(`${root}/chapters/${chapterId}`, { signal }),
  save: (chapterId: number, revision: number, document: EditDocument) => request<SingleResponse<{ revision: number; document: EditDocument; updated_at: string }>>(`${root}/chapters/${chapterId}`, { method: 'PUT', body: JSON.stringify({ revision, document }) }),
  library: (chapterId: number, resourceId: number) => request<SingleResponse<EditorMedia>>(`${root}/chapters/${chapterId}/library`, { method: 'POST', body: JSON.stringify({ resource_id: resourceId }) }),
  export: (chapterId: number, revision: number) => request<SingleResponse<EditorExport>>(`${root}/chapters/${chapterId}/exports`, { method: 'POST', body: JSON.stringify({ revision }) }),
  history: (chapterId: number) => request<SingleResponse<EditorExport[]>>(`${root}/chapters/${chapterId}/exports`),
  cancel: (taskId: string) => request(`/task/${taskId}/cancel`, { method: 'POST' }),
  async upload(chapterId: number, file: File, kind: Exclude<ClipKind, 'subtitle'>, onProgress: (percent: number) => void) {
    const form = new FormData(); form.append('file', file)
    const response = await uploadWithProgress(`${API_BASE}${root}/chapters/${chapterId}/assets?kind=${kind}`, form, authHeaders(), onProgress)
    const value = JSON.parse(response.text) as SingleResponse<EditorMedia>
    if (response.status >= 400 || value.code !== 0) throw new Error(value.message || 'Upload failed')
    return value.data
  },
}
