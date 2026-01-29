import api from './client'
import type { Chapter, ChapterDetail, ChapterWorkflowStatus, PaginatedResponse } from '@/types'

/**
 * 将后端 snake_case 响应转换为前端 camelCase 格式
 */
function transformChapter(data: Record<string, unknown>): Chapter {
  return {
    id: data.id as string,
    novelId: data.novel_id as string,
    number: data.number as number,
    title: data.title as string,
    status: data.status as Chapter['status'],
    workflowStatus: (data.workflow_status ?? 'pending') as ChapterWorkflowStatus,
    sceneCount: data.scene_count as number,
    createdAt: data.created_at as string,
  }
}

function transformChapterDetail(data: Record<string, unknown>): ChapterDetail {
  return {
    ...transformChapter(data),
    content: data.content as string,
    metadata: (data.metadata ?? {}) as Record<string, unknown>,
  }
}

export async function getChapters(
  novelId: string,
  page: number = 1,
  pageSize: number = 20
): Promise<PaginatedResponse<Chapter>> {
  const response = await api.get('/chapters', {
    params: { novel_id: novelId, page, page_size: pageSize }
  })
  const data = response.data
  return {
    items: (data.items as Record<string, unknown>[]).map(transformChapter),
    total: data.total,
    page: data.page,
    pageSize: data.page_size,
    totalPages: data.total_pages,
  }
}

export async function getChapter(id: string): Promise<ChapterDetail> {
  const response = await api.get(`/chapters/${id}`)
  return transformChapterDetail(response.data)
}

export async function updateChapter(
  id: string,
  data: { title?: string; content?: string }
): Promise<Chapter> {
  const response = await api.put(`/chapters/${id}`, data)
  return transformChapter(response.data)
}

export async function deleteChapter(id: string): Promise<void> {
  await api.delete(`/chapters/${id}`)
}

export async function createChapter(
  novelId: string,
  data: { title: string; content?: string; number?: number }
): Promise<Chapter> {
  const response = await api.post('/chapters', data, {
    params: { novel_id: novelId }
  })
  return transformChapter(response.data)
}

export async function updateChapterWorkflowStatus(
  chapterId: string,
  workflowStatus: ChapterWorkflowStatus
): Promise<Chapter> {
  const response = await api.patch(`/chapters/${chapterId}/workflow-status`, {
    workflow_status: workflowStatus
  })
  return transformChapter(response.data)
}
