import type {
  Novel, Chapter, Asset, Scene, Video, AiModelConfig, AiTask,
  PaginationResponse, SingleResponse, AllEnums,
} from '../types';

const BASE = '/api';

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(BASE + url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const json = await res.json();
  if (json.code !== 0) throw new Error(json.message || 'Request failed');
  return json;
}

function qs(params: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') parts.push(`${k}=${encodeURIComponent(String(v))}`);
  }
  return parts.length ? '?' + parts.join('&') : '';
}

class ApiService {
  // --- Enums ---
  getEnums(): Promise<SingleResponse<AllEnums>> {
    return request('/config/enums/all');
  }

  // --- Novels ---
  getNovels(page = 1, pageSize = 20): Promise<PaginationResponse<Novel>> {
    return request(`/novel${qs({ page, page_size: pageSize })}`);
  }
  getNovel(id: number): Promise<SingleResponse<Novel>> {
    return request(`/novel/${id}`);
  }
  createNovel(data: Partial<Novel>): Promise<SingleResponse<Novel>> {
    return request('/novel', { method: 'POST', body: JSON.stringify(data) });
  }
  updateNovel(id: number, data: Partial<Novel>): Promise<SingleResponse<Novel>> {
    return request(`/novel/${id}`, { method: 'PUT', body: JSON.stringify(data) });
  }
  patchNovel(id: number, data: Partial<Novel>): Promise<SingleResponse<Novel>> {
    return request(`/novel/${id}`, { method: 'PATCH', body: JSON.stringify(data) });
  }
  deleteNovel(id: number): Promise<SingleResponse<null>> {
    return request(`/novel/${id}`, { method: 'DELETE' });
  }
  splitNovel(id: number): Promise<SingleResponse<Novel>> {
    return request(`/novel/${id}/split`);
  }

  // --- Chapters ---
  getChapters(novelId: number, page = 1, pageSize = 50): Promise<PaginationResponse<Chapter>> {
    return request(`/chapter${qs({ novel_id: novelId, page, page_size: pageSize, sort: 'number' })}`);
  }
  getChapter(id: number): Promise<SingleResponse<Chapter>> {
    return request(`/chapter/${id}`);
  }
  patchChapter(id: number, data: Partial<Chapter>): Promise<SingleResponse<Chapter>> {
    return request(`/chapter/${id}`, { method: 'PATCH', body: JSON.stringify(data) });
  }
  deleteChapter(id: number): Promise<SingleResponse<null>> {
    return request(`/chapter/${id}`, { method: 'DELETE' });
  }
  extractEntities(chapterId: number): Promise<SingleResponse<AiTask>> {
    return request(`/chapter/extract/${chapterId}`, { method: 'POST' });
  }

  // --- Assets ---
  getAssets(novelId: number, page = 1, pageSize = 100): Promise<PaginationResponse<Asset>> {
    return request(`/asset${qs({ novel_id: novelId, page, page_size: pageSize })}`);
  }
  createAsset(data: Partial<Asset>): Promise<SingleResponse<Asset>> {
    return request('/asset', { method: 'POST', body: JSON.stringify(data) });
  }
  deleteAsset(id: number): Promise<SingleResponse<null>> {
    return request(`/asset/${id}`, { method: 'DELETE' });
  }
  updateAsset(id: number, data: Partial<Asset>): Promise<SingleResponse<Asset>> {
    return request(`/asset/${id}`, { method: 'PATCH', body: JSON.stringify(data) });
  }
  generateAssetImage(assetId: number): Promise<SingleResponse<AiTask>> {
    return request(`/asset/reference/${assetId}`);
  }
  async uploadFiles(files: File[]): Promise<{ data: { total: number; files: { filename: string; file_path: string }[] } }> {
    const formData = new FormData();
    files.forEach((f) => formData.append('files', f));
    const res = await fetch(BASE + '/file/upload', { method: 'POST', body: formData });
    const json = await res.json();
    if (json.code !== 0) throw new Error(json.message || 'Upload failed');
    return json;
  }

  // --- Scenes ---
  getScenes(chapterId: number, page = 1, pageSize = 100): Promise<PaginationResponse<Scene>> {
    return request(`/scene${qs({ chapter_id: chapterId, page, page_size: pageSize, sort: 'sequence' })}`);
  }
  getScene(id: number): Promise<SingleResponse<Scene>> {
    return request(`/scene/${id}`);
  }
  patchScene(id: number, data: Partial<Scene>): Promise<SingleResponse<Scene>> {
    return request(`/scene/${id}`, { method: 'PATCH', body: JSON.stringify(data) });
  }
  deleteScene(id: number): Promise<SingleResponse<null>> {
    return request(`/scene/${id}`, { method: 'DELETE' });
  }
  generateScenes(data: { chapter_id: number }): Promise<SingleResponse<AiTask>> {
    return request('/scene/generate/', { method: 'POST', body: JSON.stringify(data) });
  }

  // --- Videos ---
  getVideos(page = 1, pageSize = 20, sort = '-id', sceneId?: number): Promise<PaginationResponse<Video>> {
    return request(`/video${qs({ page, page_size: pageSize, sort, scene_id: sceneId })}`);
  }
  getVideo(id: number): Promise<SingleResponse<Video>> {
    return request(`/video/${id}`);
  }
  generateVideo(data: { scene_id: number; model_type: number }): Promise<SingleResponse<Video>> {
    return request('/video/generate/', { method: 'POST', body: JSON.stringify(data) });
  }
  queryVideo(id: number): Promise<SingleResponse<Video>> {
    return request(`/video/query/${id}`);
  }
  deleteVideo(id: number): Promise<SingleResponse<null>> {
    return request(`/video/${id}`, { method: 'DELETE' });
  }

  // --- Model Config ---
  getConfigs(page = 1, pageSize = 50): Promise<PaginationResponse<AiModelConfig>> {
    return request(`/config${qs({ page, page_size: pageSize })}`);
  }
  getConfig(id: number): Promise<SingleResponse<AiModelConfig>> {
    return request(`/config/${id}`);
  }
  createConfig(data: Partial<AiModelConfig>): Promise<SingleResponse<AiModelConfig>> {
    return request('/config', { method: 'POST', body: JSON.stringify(data) });
  }
  patchConfig(id: number, data: Partial<AiModelConfig>): Promise<SingleResponse<AiModelConfig>> {
    return request(`/config/${id}`, { method: 'PATCH', body: JSON.stringify(data) });
  }
  deleteConfig(id: number): Promise<SingleResponse<null>> {
    return request(`/config/${id}`, { method: 'DELETE' });
  }
  activateConfig(id: number): Promise<SingleResponse<AiModelConfig>> {
    return request(`/config/${id}/activate`, { method: 'POST' });
  }

  // --- Tasks ---
  getTask(id: string): Promise<SingleResponse<AiTask>> {
    return request(`/task/${id}`);
  }
}

export const api = new ApiService();
