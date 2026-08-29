import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import type { WorkbenchBootstrap } from '@/types'
import { AssetTypeEnum, TaskStatusEnum } from '@/types'
import { useWorkbenchStore } from './workbenchStore'

vi.mock('@/api', () => ({
  api: {
    workbenchBootstrap: vi.fn(),
    videoGenerationModels: vi.fn(),
    imageGenerationModels: vi.fn(),
    task: vi.fn(),
    retryRemakeSource: vi.fn(),
  },
  mediaUrl: (value: string) => value,
  persistedMediaRef: vi.fn(),
}))

const timestamp = '2026-08-28T08:00:00+08:00'
const runningBootstrap = (): WorkbenchBootstrap => ({
  chapter: { id: 11, novel_id: 7, number: 1, name: '第1集', created_at: timestamp, updated_at: timestamp },
  project_config: {
    workflow_kind: 'remake',
    aspect_ratio: '16:9',
    resolution: '1080p',
    style_key: 'cinematic',
    custom_style_prompt: null,
  },
  remake_source: {
    id: 21,
    episode_number: 1,
    source_kind: 'upload',
    media_url: '/media/remake/source.mp4',
    original_filename: '第一集.mp4',
    mime_type: 'video/mp4',
    size_bytes: 1024,
    duration_seconds: 65,
    width: 1920,
    height: 1080,
    media_status: 'processing',
    analysis_task: {
      id: 'task-1',
      status: TaskStatusEnum.PROCESSING,
      stage: 'detecting_scenes',
      progress: 42,
      error_message: null,
      created_at: timestamp,
      updated_at: timestamp,
    },
  },
  assets: [],
  scenes: [],
  videos: {},
})

let store: ReturnType<typeof useWorkbenchStore>

beforeEach(() => {
  setActivePinia(createPinia())
  store = useWorkbenchStore()
})

it('maps a remake source and running decomposition task into derived canvas nodes', () => {
  const bootstrap = runningBootstrap()
  store.chapter = bootstrap.chapter
  store.projectConfig = bootstrap.project_config!
  store.remakeSource = bootstrap.remake_source!

  store.rebuildGraph()

  expect(store.nodeByKey('remake-source-21')).toMatchObject({
    kind: 'source_video',
    data: { source: { original_filename: '第一集.mp4' } },
  })
  expect(store.nodeByKey('remake-analysis-task-1')).toMatchObject({
    kind: 'ai_decomposition',
    status: 'running',
    data: { task: { stage: 'detecting_scenes', progress: 42 } },
  })
  expect(store.edges).toEqual(expect.arrayContaining([
    expect.objectContaining({ source: 'remake-source-21', target: 'remake-analysis-task-1' }),
  ]))
})

it('hides the temporary task after completion and maps generated assets and shots once', () => {
  const bootstrap = runningBootstrap()
  bootstrap.remake_source!.media_status = 'completed'
  bootstrap.remake_source!.analysis_task = {
    ...bootstrap.remake_source!.analysis_task!,
    status: TaskStatusEnum.COMPLETED,
    stage: 'completed',
    progress: 100,
  }
  bootstrap.assets = [{
    id: 31,
    novel_id: 7,
    asset_type: AssetTypeEnum.PERSON,
    canonical_name: '女主角',
    created_at: timestamp,
    updated_at: timestamp,
  }]
  bootstrap.scenes = [{ id: 41, chapter_id: 11, sequence: 1, created_at: timestamp, updated_at: timestamp }]
  bootstrap.videos = { 41: [] }
  store.chapter = bootstrap.chapter
  store.projectConfig = bootstrap.project_config!
  store.remakeSource = bootstrap.remake_source!
  store.assets = bootstrap.assets
  store.scenes = bootstrap.scenes
  store.videos = bootstrap.videos

  store.rebuildGraph()
  store.rebuildGraph()

  expect(store.nodes.filter(node => node.key === 'asset-31')).toHaveLength(1)
  expect(store.nodes.filter(node => node.key === 'shot-41')).toHaveLength(1)
  expect(store.nodes.some(node => node.kind === 'ai_decomposition')).toBe(false)
  expect(store.nodeByKey('shot-41')?.data.project_defaults).toEqual({ aspectRatio: '16:9', resolution: '1080p' })
})

it('refreshes the current working set when decomposition polling completes', async () => {
  const initial = runningBootstrap()
  const completed = runningBootstrap()
  completed.remake_source!.media_status = 'completed'
  completed.remake_source!.analysis_task = {
    ...completed.remake_source!.analysis_task!,
    status: TaskStatusEnum.COMPLETED,
    stage: 'completed',
    progress: 100,
  }
  completed.assets = [{ id: 31, novel_id: 7, asset_type: AssetTypeEnum.SCENE, canonical_name: '街道', created_at: timestamp, updated_at: timestamp }]
  completed.scenes = [{ id: 41, chapter_id: 11, sequence: 1, created_at: timestamp, updated_at: timestamp }]
  completed.videos = { 41: [] }
  store.novelId = 7
  store.chapterId = 11
  store.chapter = initial.chapter
  store.projectConfig = initial.project_config!
  store.remakeSource = initial.remake_source!
  vi.mocked(api.task).mockResolvedValueOnce({ code: 0, message: 'ok', data: completed.remake_source!.analysis_task! } as never)
  vi.mocked(api.workbenchBootstrap).mockResolvedValueOnce({ code: 0, message: 'ok', data: completed })

  await store.resumeRemakeAnalysis()

  expect(api.workbenchBootstrap).toHaveBeenCalledWith(7, 11)
  expect(store.nodeByKey('asset-31')).toBeTruthy()
  expect(store.nodeByKey('shot-41')).toBeTruthy()
  expect(store.nodes.some(node => node.kind === 'ai_decomposition')).toBe(false)
})

it('retries a failed source and resumes it with a new task', async () => {
  const bootstrap = runningBootstrap()
  bootstrap.remake_source!.media_status = 'failed'
  bootstrap.remake_source!.analysis_task = {
    ...bootstrap.remake_source!.analysis_task!,
    status: TaskStatusEnum.FAILED,
    stage: 'failed',
    error_message: '拆解失败',
  }
  store.novelId = 7
  store.chapterId = 11
  store.chapter = bootstrap.chapter
  store.projectConfig = bootstrap.project_config!
  store.remakeSource = bootstrap.remake_source!
  vi.mocked(api.retryRemakeSource).mockResolvedValueOnce({
    code: 0,
    message: 'ok',
    data: { source_id: 21, task_id: 'task-2', status: TaskStatusEnum.QUEUED },
  } as never)
  vi.spyOn(store, 'resumeRemakeAnalysis').mockResolvedValue()

  await store.retryRemakeAnalysis()

  expect(api.retryRemakeSource).toHaveBeenCalledWith(7, 21)
  expect(store.remakeSource.analysis_task).toMatchObject({ id: 'task-2', status: TaskStatusEnum.QUEUED, progress: 0 })
  expect(store.resumeRemakeAnalysis).toHaveBeenCalled()
})
