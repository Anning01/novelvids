import api from '@/api/client'

export type ExtractionTaskType = 'person' | 'scene' | 'item'

export interface ExtractionTask {
  id: string
  chapter_id: string
  task_type: ExtractionTaskType
  status: 'pending' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  progress: number
  message: string | null
  retry_count: number
  result: {
    count?: number
    entities?: Array<{
      name: string
      entity_type: string
      description: string
      base_traits: string
      aliases: string[]
      appearances: Array<{ line: number; context: string }>
    }>
  } | null
  error: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface ChapterExtractionStatus {
  chapter_id: string
  person: ExtractionTask | null
  scene: ExtractionTask | null
  item: ExtractionTask | null
  overall_progress: number
  is_complete: boolean
}

export interface CreateExtractionTaskParams {
  chapter_id: string
  task_type: ExtractionTaskType
  timeout_seconds?: number
  max_retries?: number
}

export interface CreateBatchExtractionParams {
  chapter_id: string
  task_types?: ExtractionTaskType[]
  timeout_seconds?: number
}

/**
 * 创建单个提取任务
 */
export async function createExtractionTask(
  params: CreateExtractionTaskParams
): Promise<ExtractionTask> {
  const response = await api.post('/extraction/tasks', params)
  return response.data
}

/**
 * 批量创建提取任务
 */
export async function createBatchExtractionTasks(
  params: CreateBatchExtractionParams
): Promise<ExtractionTask[]> {
  const response = await api.post('/extraction/tasks/batch', params)
  return response.data
}

/**
 * 获取任务详情（用于轮询）
 */
export async function getExtractionTask(taskId: string): Promise<ExtractionTask> {
  const response = await api.get(`/extraction/tasks/${taskId}`)
  return response.data
}

/**
 * 获取章节的提取状态汇总
 */
export async function getChapterExtractionStatus(
  chapterId: string
): Promise<ChapterExtractionStatus> {
  const response = await api.get(`/extraction/chapters/${chapterId}/status`)
  return response.data
}

/**
 * 重试失败的任务
 */
export async function retryExtractionTask(taskId: string): Promise<ExtractionTask> {
  const response = await api.post(`/extraction/tasks/${taskId}/retry`)
  return response.data
}

/**
 * 取消任务
 */
export async function cancelExtractionTask(taskId: string): Promise<void> {
  await api.delete(`/extraction/tasks/${taskId}`)
}

/**
 * 轮询配置
 */
export interface PollingConfig {
  intervalMs: number
  maxAttempts: number
  onProgress?: (task: ExtractionTask) => void
}

const DEFAULT_POLLING_CONFIG: PollingConfig = {
  intervalMs: 2000,
  maxAttempts: 60, // 最多轮询 2 分钟
}

/**
 * 轮询任务直到完成
 */
export async function pollTaskUntilComplete(
  taskId: string,
  config: Partial<PollingConfig> = {}
): Promise<ExtractionTask> {
  const { intervalMs, maxAttempts, onProgress } = { ...DEFAULT_POLLING_CONFIG, ...config }

  let attempts = 0

  while (attempts < maxAttempts) {
    const task = await getExtractionTask(taskId)

    if (onProgress) {
      onProgress(task)
    }

    if (task.status === 'completed' || task.status === 'failed' || task.status === 'cancelled') {
      return task
    }

    await new Promise((resolve) => setTimeout(resolve, intervalMs))
    attempts++
  }

  throw new Error('Polling timeout: task did not complete in time')
}

/**
 * 轮询章节所有任务直到完成
 */
export async function pollChapterExtractionUntilComplete(
  chapterId: string,
  config: Partial<PollingConfig> = {}
): Promise<ChapterExtractionStatus> {
  const { intervalMs, maxAttempts } = { ...DEFAULT_POLLING_CONFIG, ...config }

  let attempts = 0

  while (attempts < maxAttempts) {
    const status = await getChapterExtractionStatus(chapterId)

    // 检查是否所有任务都完成或失败
    const tasks = [status.person, status.scene, status.item].filter(Boolean) as ExtractionTask[]
    const allDone = tasks.every(
      (t) => t.status === 'completed' || t.status === 'failed' || t.status === 'cancelled'
    )

    if (allDone && tasks.length > 0) {
      return status
    }

    await new Promise((resolve) => setTimeout(resolve, intervalMs))
    attempts++
  }

  throw new Error('Polling timeout: extraction did not complete in time')
}
