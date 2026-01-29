import api from './client'
import type { Novel, NovelDetail, PaginatedResponse, WorkflowStatus } from '@/types'

/**
 * 将后端 snake_case 响应转换为前端 camelCase 格式
 */
function transformNovel(data: Record<string, unknown>): Novel {
  return {
    id: data.id as string,
    title: data.title as string,
    author: data.author as string | null,
    status: data.status as Novel['status'],
    workflowStatus: (data.workflow_status ?? 'draft') as WorkflowStatus,
    totalChapters: data.total_chapters as number,
    processedChapters: data.processed_chapters as number,
    createdAt: data.created_at as string,
    updatedAt: data.updated_at as string,
  }
}

function transformNovelDetail(data: Record<string, unknown>): NovelDetail {
  return {
    ...transformNovel(data),
    content: (data.content as string | null) ?? null,
    metadata: (data.metadata ?? {}) as Record<string, unknown>,
    canExtractChapters: (data.can_extract_chapters ?? false) as boolean,
    canExtractCharacters: (data.can_extract_characters ?? false) as boolean,
    canCreateStoryboard: (data.can_create_storyboard ?? false) as boolean,
    canGenerateVideo: (data.can_generate_video ?? false) as boolean,
  }
}

export async function getNovels(
  page: number = 1,
  pageSize: number = 20
): Promise<PaginatedResponse<Novel>> {
  const response = await api.get('/novels', { params: { page, page_size: pageSize } })
  const data = response.data
  return {
    items: (data.items as Record<string, unknown>[]).map(transformNovel),
    total: data.total,
    page: data.page,
    pageSize: data.page_size,
    totalPages: data.total_pages,
  }
}

export async function getNovel(id: string): Promise<NovelDetail> {
  const response = await api.get(`/novels/${id}`)
  return transformNovelDetail(response.data)
}

export async function createNovel(data: {
  title: string
  content?: string
  author?: string
}): Promise<Novel> {
  const response = await api.post('/novels', data)
  return transformNovel(response.data)
}

export async function updateNovel(
  id: string,
  data: { title?: string; content?: string; author?: string }
): Promise<Novel> {
  const response = await api.put(`/novels/${id}`, data)
  return transformNovel(response.data)
}

export async function deleteNovel(id: string): Promise<void> {
  await api.delete(`/novels/${id}`)
}

export async function extractChapters(id: string): Promise<Novel> {
  const response = await api.post(`/novels/${id}/extract-chapters`)
  return transformNovel(response.data)
}
