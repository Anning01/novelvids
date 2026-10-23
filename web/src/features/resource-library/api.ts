import { API_BASE, authHeaders, request, uploadWithProgress } from '@/api'
import type { PaginationResponse, SingleResponse, VideoReferenceMedia } from '@/types'
import type { DeleteResult, LibraryCapabilities, ResourceFolder, ResourceImport, VideoResource } from './types'

const root = '/resource-library'
const json = (method: string, data: unknown) => ({ method, body: JSON.stringify(data) })
export const libraryApi = {
  capabilities: () => request<SingleResponse<LibraryCapabilities>>(`${root}/capabilities`),
  get: (id: number) => request<SingleResponse<VideoResource>>(`${root}/resources/${id}`),
  folders: () => request<SingleResponse<ResourceFolder[]>>(`${root}/folders`),
  list: (folder: number | null, search: string, page = 1) => {
    const query = new URLSearchParams({ search, page: String(page) })
    if (folder !== null) query.set('folder_id', String(folder))
    return request<PaginationResponse<VideoResource>>(`${root}/resources?${query}`)
  },
  writeFolder: (name: string, parent_id: number, id?: number) => request<SingleResponse<ResourceFolder>>(`${root}/folders${id ? `/${id}` : ''}`, json(id ? 'PUT' : 'POST', { name, parent_id })),
  move: (ids: number[], folder_id: number) => request(`${root}/move`, json('POST', { ids, folder_id })),
  rename: (id: number, name: string) => request(`${root}/resources/${id}`, json('PATCH', { name })),
  delete: (ids: number[]) => request<SingleResponse<DeleteResult[]>>(`${root}/delete`, json('POST', { ids })),
  deletePreview: (id: number) => request<SingleResponse<{ resource_count: number; folder_count: number }>>(`${root}/folders/${id}/delete-preview`),
  deleteFolder: (id: number) => request<SingleResponse<DeleteResult[]>>(`${root}/folders/${id}`, { method: 'DELETE' }),
  import: (data: ResourceImport) => request<SingleResponse<VideoResource>>(`${root}/import`, json('POST', data)),
  select: (ids: number[], model_config_id: number) => request<SingleResponse<VideoReferenceMedia[]>>(`${root}/selection`, json('POST', { ids, model_config_id })),
  async upload(file: File, folderId: number, onProgress?: (percent: number) => void, source = false): Promise<VideoResource> {
    // Pin both folder and team for the entire upload, including OSS finalization.
    const headers = authHeaders()
    const jsonHeaders = { ...headers, 'Content-Type': 'application/json' }
    const policy = await request<SingleResponse<{ direct: boolean; resource_id?: number; upload_url?: string; fields?: Record<string, string> }>>(`${root}/upload-policy?source=${source}`, {
      ...json('POST', { filename: file.name, folder_id: folderId }), headers: jsonHeaders,
    })
    onProgress?.(0)
    const form = new FormData()
    if (policy.data.direct) {
      Object.entries(policy.data.fields ?? {}).forEach(([key, value]) => form.append(key, value))
      form.append('file', file)
      try {
        const result = await uploadWithProgress(policy.data.upload_url!, form, {}, onProgress)
        if (result.status < 200 || result.status >= 300) throw new Error('直传失败，请重试')
        onProgress?.(100)
        const response = await request<SingleResponse<VideoResource>>(`${root}/resources/${policy.data.resource_id}/finalize`, { method: 'POST', headers: jsonHeaders })
        return response.data
      } catch (reason) {
        await request(`${root}/resources/${policy.data.resource_id}/cancel-upload`, { method: 'POST', headers: jsonHeaders }).catch(() => undefined)
        throw reason
      }
    }
    form.append('file', file)
    form.append('folder_id', String(folderId))
    form.append('source', String(source))
    const result = await uploadWithProgress(`${API_BASE}${root}/upload`, form, headers, onProgress)
    const payload = JSON.parse(result.text) as SingleResponse<VideoResource>
    if (result.status >= 400 || payload.code !== 0) throw new Error(payload.message || '视频上传失败')
    return payload.data
  },
}
