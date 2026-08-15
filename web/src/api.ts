import type { AiModelConfig, AiTask, AllEnums, Asset, AssetGenerationRecord, AssetMergeResult, AssetReferencePromptPreview, AssetVariant, AudioReference, BillingProject, BillingProjectDetail, BillingRecord, BillingSummary, Chapter, DigitalHuman, GeneralConfig, GenerationCapabilities, ImageGenerationModel, Novel, PaginationResponse, Scene, SingleResponse, Video, VideoGenerationModel, VideoReferenceMedia, WorkbenchBootstrap, WorkbenchCapabilities } from './types'

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

async function requestAllPages<T>(urlForPage: (page: number, pageSize: number) => string, pageSize = 100): Promise<PaginationResponse<T>> {
  const first = await request<PaginationResponse<T>>(urlForPage(1, pageSize))
  const pageCount = first.data.pagination.pages
  if (pageCount <= 1) return first
  const remaining: PaginationResponse<T>[] = []
  // 有上千章节时也不一次性并发打满服务端；按小批次顺序聚合全部页。
  for (let firstPage = 2; firstPage <= pageCount; firstPage += 4) {
    const lastPage = Math.min(pageCount, firstPage + 3)
    const batch = await Promise.all(
      Array.from(
        { length: lastPage - firstPage + 1 },
        (_, index) => request<PaginationResponse<T>>(urlForPage(firstPage + index, pageSize)),
      ),
    )
    remaining.push(...batch)
  }
  const items = [first, ...remaining].flatMap(response => response.data.items)
  return {
    ...first,
    data: {
      items,
      pagination: { ...first.data.pagination, total: items.length, page: 1, page_size: items.length },
    },
  }
}

export const api = {
  enums: () => request<SingleResponse<AllEnums>>('/config/enums/all'),
  novels: () => request<PaginationResponse<Novel>>('/novel?page=1&page_size=100'),
  novel: (id: number) => request<SingleResponse<Novel>>(`/novel/${id}`),
  createNovel: (data: Partial<Novel>) => request<SingleResponse<Novel>>('/novel', { method: 'POST', body: JSON.stringify(data) }),
  updateNovel: (id: number, data: Partial<Novel>) => request<SingleResponse<Novel>>(`/novel/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteNovel: (id: number) => request<SingleResponse<null>>(`/novel/${id}`, { method: 'DELETE' }),
  splitNovel: (id: number) => request<SingleResponse<Novel>>(`/novel/${id}/split`, { method: 'POST' }),
  analyzeNovel: (id: number) => request<SingleResponse<AiTask>>(`/novel/${id}/analyze`, { method: 'POST' }),
  novelAnalysis: (id: number) => request<SingleResponse<AiTask | null>>(`/novel/${id}/analysis`),
  chapters: (novelId: number) => requestAllPages<Chapter>(
    (page, pageSize) => `/chapter${qs({ novel_id: novelId, page, page_size: pageSize, sort: 'number' })}`,
  ),
  chapter: (id: number) => request<SingleResponse<Chapter>>(`/chapter/${id}`),
  createChapter: (data: Partial<Chapter>) => request<SingleResponse<Chapter>>('/chapter', { method: 'POST', body: JSON.stringify(data) }),
  updateChapter: (id: number, data: Partial<Chapter>) => request<SingleResponse<Chapter>>(`/chapter/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteChapter: (id: number) => request<SingleResponse<null>>(`/chapter/${id}`, { method: 'DELETE' }),
  extract: (chapterId: number) => request<SingleResponse<AiTask>>(`/chapter/extract/${chapterId}`, { method: 'POST' }),
  latestExtraction: (chapterId: number) => request<SingleResponse<AiTask | null>>(`/chapter/extract/${chapterId}/latest`),
  assets: (novelId: number, page = 1, pageSize = 100, chapterId?: number) => request<PaginationResponse<Asset>>(`/asset${qs({ novel_id: novelId, page, page_size: pageSize, chapter_id: chapterId })}`),
  referencePromptPreview: (data: Pick<Asset, 'asset_type' | 'canonical_name' | 'base_traits' | 'description' | 'metadata'> & { aspect_ratio?: string }) => request<SingleResponse<AssetReferencePromptPreview>>('/asset/reference-prompt/preview', { method: 'POST', body: JSON.stringify(data) }),
  projectAssetLibrary: (novelId: number, page = 1, search = '', pageSize = 24, assetType?: number) => request<PaginationResponse<Asset>>(`/asset${qs({ novel_id: novelId, asset_type: assetType, page, page_size: pageSize, search, sort: 'canonical_name' })}`),
  publicAssetLibrary: (assetType: number, page = 1, search = '', pageSize = 24) => request<PaginationResponse<Asset>>(`/asset${qs({ asset_type: assetType, is_global: true, page, page_size: pageSize, search, sort: 'canonical_name' })}`),
  asset: (id: number) => request<SingleResponse<Asset>>(`/asset/${id}`),
  assetGenerationHistory: (id: number) => request<SingleResponse<AssetGenerationRecord[]>>(`/asset/${id}/generation-history`),
  recordAssetImageEdit: (id: number, data: { image_url: string; source_image_url?: string; output_format?: string }) => request<SingleResponse<Asset>>(`/asset/${id}/generation-history/edit`, { method: 'POST', body: JSON.stringify(data) }),
  restoreAssetGeneration: (assetId: number, taskId: string) => request<SingleResponse<Asset>>(`/asset/${assetId}/generation-history/${taskId}/restore`, { method: 'POST' }),
  assetLibrary: (assetType: number, page = 1, pageSize = 24) => request<PaginationResponse<Asset>>(`/asset${qs({ asset_type: assetType, page, page_size: pageSize, sort: '-id' })}`),
  createAsset: (data: Partial<Asset> & { novel_id: number; chapter_id?: number; asset_type: number; canonical_name: string }) => request<SingleResponse<Asset>>('/asset', { method: 'POST', body: JSON.stringify(data) }),
  updateAsset: (id: number, data: Partial<Asset>) => request<SingleResponse<Asset>>(`/asset/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteAsset: (id: number) => request<SingleResponse<null>>(`/asset/${id}`, { method: 'DELETE' }),
  mergeAssets: (sourceAssetId: number, targetAssetId: number) => request<SingleResponse<AssetMergeResult>>('/asset/merge', { method: 'POST', body: JSON.stringify({ source_asset_id: sourceAssetId, target_asset_id: targetAssetId }) }),
  reuseAsset: (assetId: number, chapterId: number) => request<SingleResponse<Asset>>(`/asset/${assetId}/chapters/${chapterId}`, { method: 'POST' }),
  assetVariants: (assetId: number) => request<SingleResponse<AssetVariant[]>>(`/asset/${assetId}/variants`),
  createAssetVariant: (assetId: number, data: Partial<AssetVariant> & { name: string }) => request<SingleResponse<AssetVariant>>(`/asset/${assetId}/variants`, { method: 'POST', body: JSON.stringify(data) }),
  updateAssetVariant: (assetId: number, variantId: number, data: Partial<AssetVariant>) => request<SingleResponse<AssetVariant>>(`/asset/${assetId}/variants/${variantId}`, { method: 'PATCH', body: JSON.stringify(data) }),
  assignAssetVariantToChapter: (assetId: number, variantId: number, chapterNumber: number) => request<SingleResponse<AssetVariant[]>>(`/asset/${assetId}/variants/${variantId}/chapter`, { method: 'POST', body: JSON.stringify({ chapter_number: chapterNumber }) }),
  deleteAssetVariant: (assetId: number, variantId: number) => request<SingleResponse<null>>(`/asset/${assetId}/variants/${variantId}`, { method: 'DELETE' }),
  generateAsset: (id: number, variantId?: number) => request<SingleResponse<AiTask>>(`/asset/reference/${id}${qs({ variant_id: variantId })}`),
  scenes: (chapterId: number) => request<PaginationResponse<Scene>>(`/scene${qs({ chapter_id: chapterId, page: 1, page_size: 100, sort: 'sequence' })}`),
  scene: (id: number) => request<SingleResponse<Scene>>(`/scene/${id}`),
  createScene: (data: Partial<Scene> & { chapter_id: number; sequence: number; prompt: string }) => request<SingleResponse<Scene>>('/scene/', { method: 'POST', body: JSON.stringify(data) }),
  insertSceneAfter: (sceneId: number) => request<SingleResponse<Scene>>(`/scene/${sceneId}/insert-after`, { method: 'POST' }),
  updateScene: (id: number, data: Partial<Scene>) => request<SingleResponse<Scene>>(`/scene/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteScene: (id: number) => request<SingleResponse<null>>(`/scene/${id}`, { method: 'DELETE' }),
  generateScenes: (chapterId: number) => request<SingleResponse<AiTask>>('/scene/generate/', { method: 'POST', body: JSON.stringify({ chapter_id: chapterId }) }),
  videos: (sceneId?: number) => request<PaginationResponse<Video>>(`/video${qs({ page: 1, page_size: 100, sort: '-id', scene_id: sceneId })}`),
  videoGenerationHistory: (sceneId: number) => request<SingleResponse<Video[]>>(`/video/scene/${sceneId}/generation-history`),
  selectCurrentVideo: (videoId: number) => request<SingleResponse<Video>>(`/video/${videoId}/select-current`, { method: 'POST' }),
  generateVideo: (sceneId: number, modelConfigId: number, options: { generation_mode?: 'reference' | 'keyframes'; first_frame_url?: string; last_frame_url?: string; resolution?: string; aspect_ratio?: string; duration?: number; output_format?: string; generate_audio?: boolean; return_last_frame?: boolean; reference_media?: VideoReferenceMedia[] } = {}) => request<SingleResponse<Video>>('/video/generate/', { method: 'POST', body: JSON.stringify({ scene_id: sceneId, model_config_id: modelConfigId, ...options }) }),
  async uploadVideoReference(file: File, modelConfigId: number) {
    const data = new FormData()
    data.append('model_config_id', String(modelConfigId))
    data.append('file', file)
    const response = await fetch(`${BASE}/video/reference/upload`, { method: 'POST', body: data })
    const payload = await response.json()
    if (!response.ok || payload.code !== 0) throw new Error(payload.message || payload.detail || '参考素材上传失败')
    return payload.data as VideoReferenceMedia
  },
  queryVideo: (id: number) => request<SingleResponse<Video>>(`/video/query/${id}`),
  deleteVideo: (id: number) => request<SingleResponse<null>>(`/video/${id}`, { method: 'DELETE' }),
  audioReferences: (page = 1, search = '', filters: Record<string, string | number | undefined> = {}) => request<PaginationResponse<AudioReference>>(`/media-library/audio-references${qs({ page, page_size: 24, search, sort: 'id', ...filters })}`),
  digitalHumans: (page = 1, search = '', filters: Record<string, string | number | undefined> = {}) => request<PaginationResponse<DigitalHuman>>(`/media-library/digital-humans${qs({ page, page_size: 24, search, sort: 'id', ...filters })}`),
  workbenchCapabilities: () => request<SingleResponse<WorkbenchCapabilities>>('/workbench/capabilities'),
  workbenchBootstrap: (novelId: number, chapterId: number) => request<SingleResponse<WorkbenchBootstrap>>(`/workbench/bootstrap${qs({ novel_id: novelId, chapter_id: chapterId })}`),
  configs: () => request<PaginationResponse<AiModelConfig>>('/config?page=1&page_size=100'),
  imageGenerationModels: () => request<SingleResponse<ImageGenerationModel[]>>('/config/image-generation/models'),
  videoGenerationModels: () => request<SingleResponse<VideoGenerationModel[]>>('/config/video-generation/models'),
  generationCapabilities: () => request<SingleResponse<GenerationCapabilities>>('/config/generation/capabilities'),
  generalConfig: () => request<SingleResponse<GeneralConfig>>('/config/general'),
  updateGeneralConfig: (data: Pick<GeneralConfig, 'prompt_language'>) => request<SingleResponse<GeneralConfig>>('/config/general', { method: 'PUT', body: JSON.stringify(data) }),
  createConfig: (data: Partial<AiModelConfig>) => request<SingleResponse<AiModelConfig>>('/config', { method: 'POST', body: JSON.stringify(data) }),
  updateConfig: (id: number, data: Partial<AiModelConfig>) => request<SingleResponse<AiModelConfig>>(`/config/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  activateConfig: (id: number) => request<SingleResponse<AiModelConfig>>(`/config/${id}/activate`, { method: 'POST' }),
  deactivateConfig: (id: number) => request<SingleResponse<AiModelConfig>>(`/config/${id}/deactivate`, { method: 'POST' }),
  deleteConfig: (id: number) => request<SingleResponse<null>>(`/config/${id}`, { method: 'DELETE' }),
  task: (id: string) => request<SingleResponse<AiTask>>(`/task/${id}`),
  billingSummary: () => request<SingleResponse<BillingSummary>>('/billing/summary'),
  billingProjects: (page = 1, pageSize = 20) => request<PaginationResponse<BillingProject>>(`/billing/projects${qs({ page, page_size: pageSize })}`),
  billingProject: (id: number) => request<SingleResponse<BillingProjectDetail>>(`/billing/projects/${id}`),
  billingRecords: (params: { novel_id?: number; task_type?: number; billing_type?: string; status?: number; page?: number; page_size?: number } = {}) => request<PaginationResponse<BillingRecord>>(`/billing/records${qs(params)}`),
  async upload(file: File) {
    const data = new FormData(); data.append('files', file)
    const response = await fetch(`${BASE}/file/upload`, { method: 'POST', body: data })
    const payload = await response.json()
    if (!response.ok || payload.code !== 0) throw new Error(payload.message || '上传失败')
    return payload.data.files[0] as {
      filename: string
      original_filename: string
      content_type: string
      file_path: string
      text_content?: string
      chapter_validation?: { valid: boolean; chapter_count: number; text_length: number; message: string }
    }
  },
}

export const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))
export const statusLabel = (status?: number) => ({ 1: '等待中', 2: '处理中', 3: '已完成', 4: '失败', 5: '已取消', 6: '排队中' }[status || 0] || '未知')
