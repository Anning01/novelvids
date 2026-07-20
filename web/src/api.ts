import type { AiModelConfig, AiTask, AllEnums, Asset, Chapter, Novel, PaginationResponse, Scene, SingleResponse, Video } from './types'

const BASE = '/api'
async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(BASE + url, { headers: { 'Content-Type': 'application/json' }, ...options })
  const payload = await response.json()
  if (!response.ok || payload.code !== 0) throw new Error(payload.message || payload.detail || '请求失败')
  return payload
}
function qs(params: Record<string, unknown>) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => { if (value !== undefined && value !== null && value !== '') query.set(key, String(value)) })
  const value = query.toString()
  return value ? `?${value}` : ''
}

export const api = {
  enums: () => request<SingleResponse<AllEnums>>('/config/enums/all'),
  novels: () => request<PaginationResponse<Novel>>('/novel?page=1&page_size=100'),
  novel: (id: number) => request<SingleResponse<Novel>>(`/novel/${id}`),
  createNovel: (data: Partial<Novel>) => request<SingleResponse<Novel>>('/novel', { method: 'POST', body: JSON.stringify(data) }),
  deleteNovel: (id: number) => request<SingleResponse<null>>(`/novel/${id}`, { method: 'DELETE' }),
  splitNovel: (id: number) => request<SingleResponse<Novel>>(`/novel/${id}/split`, { method: 'POST' }),
  chapters: (novelId: number) => request<PaginationResponse<Chapter>>(`/chapter${qs({ novel_id: novelId, page: 1, page_size: 100, sort: 'number' })}`),
  chapter: (id: number) => request<SingleResponse<Chapter>>(`/chapter/${id}`),
  createChapter: (data: Partial<Chapter>) => request<SingleResponse<Chapter>>('/chapter', { method: 'POST', body: JSON.stringify(data) }),
  deleteChapter: (id: number) => request<SingleResponse<null>>(`/chapter/${id}`, { method: 'DELETE' }),
  extract: (chapterId: number) => request<SingleResponse<AiTask>>(`/chapter/extract/${chapterId}`, { method: 'POST' }),
  assets: (novelId: number) => request<PaginationResponse<Asset>>(`/asset${qs({ novel_id: novelId, page: 1, page_size: 200 })}`),
  updateAsset: (id: number, data: Partial<Asset>) => request<SingleResponse<Asset>>(`/asset/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteAsset: (id: number) => request<SingleResponse<null>>(`/asset/${id}`, { method: 'DELETE' }),
  generateAsset: (id: number) => request<SingleResponse<AiTask>>(`/asset/reference/${id}`),
  scenes: (chapterId: number) => request<PaginationResponse<Scene>>(`/scene${qs({ chapter_id: chapterId, page: 1, page_size: 200, sort: 'sequence' })}`),
  scene: (id: number) => request<SingleResponse<Scene>>(`/scene/${id}`),
  createScene: (data: Partial<Scene> & { chapter_id: number; sequence: number; prompt: string }) => request<SingleResponse<Scene>>('/scene/', { method: 'POST', body: JSON.stringify(data) }),
  updateScene: (id: number, data: Partial<Scene>) => request<SingleResponse<Scene>>(`/scene/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteScene: (id: number) => request<SingleResponse<null>>(`/scene/${id}`, { method: 'DELETE' }),
  generateScenes: (chapterId: number) => request<SingleResponse<AiTask>>('/scene/generate/', { method: 'POST', body: JSON.stringify({ chapter_id: chapterId }) }),
  videos: (sceneId?: number) => request<PaginationResponse<Video>>(`/video${qs({ page: 1, page_size: 100, sort: '-id', scene_id: sceneId })}`),
  generateVideo: (sceneId: number, modelType: number) => request<SingleResponse<Video>>('/video/generate/', { method: 'POST', body: JSON.stringify({ scene_id: sceneId, model_type: modelType }) }),
  queryVideo: (id: number) => request<SingleResponse<Video>>(`/video/query/${id}`),
  deleteVideo: (id: number) => request<SingleResponse<null>>(`/video/${id}`, { method: 'DELETE' }),
  configs: () => request<PaginationResponse<AiModelConfig>>('/config?page=1&page_size=100'),
  createConfig: (data: Partial<AiModelConfig>) => request<SingleResponse<AiModelConfig>>('/config', { method: 'POST', body: JSON.stringify(data) }),
  activateConfig: (id: number) => request<SingleResponse<AiModelConfig>>(`/config/${id}/activate`, { method: 'POST' }),
  deleteConfig: (id: number) => request<SingleResponse<null>>(`/config/${id}`, { method: 'DELETE' }),
  task: (id: string) => request<SingleResponse<AiTask>>(`/task/${id}`),
  async upload(file: File) {
    const data = new FormData(); data.append('files', file)
    const response = await fetch(`${BASE}/file/upload`, { method: 'POST', body: data })
    const payload = await response.json()
    if (!response.ok || payload.code !== 0) throw new Error(payload.message || '上传失败')
    return payload.data.files[0] as { filename: string; file_path: string }
  },
}

export const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))
export const statusLabel = (status?: number) => ({ 1: '等待中', 2: '处理中', 3: '已完成', 4: '失败', 5: '已取消', 6: '排队中' }[status || 0] || '未知')
