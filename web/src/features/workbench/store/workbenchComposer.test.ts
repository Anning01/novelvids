import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import type { WorkbenchNode } from '../types/workbenchTypes'
import { useWorkbenchStore } from './workbenchStore'

vi.mock('@/api', () => ({
  api: { mergeChapterVideos: vi.fn() },
  sleep: vi.fn(),
}))

let store: ReturnType<typeof useWorkbenchStore>

function source(key: string, kind: WorkbenchNode['kind']): WorkbenchNode {
  return {
    id: -1,
    key,
    kind,
    backendKind: kind,
    title: key,
    position: { x: 0, y: 0 },
    size: null,
    zIndex: 1,
    activeVersionId: null,
    status: 'ready',
    data: {},
    createdAt: '',
    updatedAt: '',
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  store = useWorkbenchStore()
  store.chapterId = 2162
  localStorage.clear()
})

it('adds a selected persistent composer with reference defaults', () => {
  vi.spyOn(Date, 'now').mockReturnValueOnce(4001)

  const created = store.addVideoComposer({ x: 120, y: 240 })

  expect(created).toMatchObject({
    key: 'video-composer-4001',
    kind: 'video_composer',
    title: '视频合成器',
    position: { x: 120, y: 240 },
    size: { width: 390, height: 420 },
  })
  expect(created.data.config).toEqual({
    name: '视频合成器',
    resolution: '720p',
    aspectRatio: '9:16',
  })
  expect(store.selectedNodeKeys).toEqual([created.key])
})

it('executes strict chapter composition and stores the downloadable result', async () => {
  vi.spyOn(Date, 'now').mockReturnValueOnce(4050)
  const composer = store.addVideoComposer()
  vi.mocked(api.mergeChapterVideos).mockResolvedValueOnce({
    code: 0,
    message: 'ok',
    data: { chapter_id: 2162, merged_url: '/media/videos/merged/chapter.mp4', video_count: 2, total_duration: 10 },
  })

  await store.composeChapter(composer.key)

  expect(api.mergeChapterVideos).toHaveBeenCalledWith(2162, true)
  expect(store.nodeByKey(composer.key)?.data.result).toEqual({
    chapter_id: 2162,
    merged_url: '/media/videos/merged/chapter.mp4',
    video_count: 2,
    total_duration: 10,
  })
})

it('connects shot, video, and watermark sources to distinct composer inputs', () => {
  vi.spyOn(Date, 'now')
    .mockReturnValueOnce(4100)
    .mockReturnValueOnce(4101)
    .mockReturnValueOnce(4102)
    .mockReturnValueOnce(4103)
  const composer = store.addVideoComposer()
  store.nodes.push(source('shot-1', 'shot'), source('video-1', 'video_media'), source('watermark-1', 'watermark'))

  store.connectMediaNode('shot-1', composer.key)
  store.connectMediaNode('video-1', composer.key)
  store.connectMediaNode('watermark-1', composer.key)

  expect(store.edges.slice(-3).map(edge => ({
    source: edge.source,
    sourceHandle: edge.sourceHandle,
    targetHandle: edge.targetHandle,
    orderIndex: edge.orderIndex,
  }))).toEqual([
    { source: 'shot-1', sourceHandle: 'sequence-output', targetHandle: 'shot-input', orderIndex: 0 },
    { source: 'video-1', sourceHandle: 'output-output', targetHandle: 'video-input', orderIndex: 1 },
    { source: 'watermark-1', sourceHandle: 'watermark-output', targetHandle: 'watermark-input', orderIndex: 0 },
  ])
})

it('preserves an explicit shot result connection to the composer video input', () => {
  vi.spyOn(Date, 'now')
    .mockReturnValueOnce(4150)
    .mockReturnValueOnce(4151)
  const composer = store.addVideoComposer()
  store.nodes.push(source('shot-1', 'shot'))

  expect(store.connectMediaNode('shot-1', composer.key, {
    sourceHandle: 'output-output',
    targetHandle: 'video-input',
  })).toBe(true)

  expect(store.edges.at(-1)).toMatchObject({
    sourceHandle: 'output-output',
    targetHandle: 'video-input',
    type: 'output_binding',
  })
})

it('moves an input and reindexes related edges through undo and redo', () => {
  vi.spyOn(Date, 'now')
    .mockReturnValueOnce(4200)
    .mockReturnValueOnce(4201)
    .mockReturnValueOnce(4202)
  const composer = store.addVideoComposer()
  store.nodes.push(source('video-a', 'video_media'), source('video-b', 'video_media'))
  store.connectMediaNode('video-a', composer.key)
  store.connectMediaNode('video-b', composer.key)

  store.moveComposerInput(composer.key, 'video-b', 'up')
  expect(store.edges.filter(edge => edge.target === composer.key).sort((a, b) => a.orderIndex - b.orderIndex).map(edge => edge.source))
    .toEqual(['video-b', 'video-a'])

  expect(store.undo()).toBe(true)
  expect(store.edges.filter(edge => edge.target === composer.key).sort((a, b) => a.orderIndex - b.orderIndex).map(edge => edge.source))
    .toEqual(['video-a', 'video-b'])

  expect(store.redo()).toBe(true)
  expect(store.edges.filter(edge => edge.target === composer.key).sort((a, b) => a.orderIndex - b.orderIndex).map(edge => edge.source))
    .toEqual(['video-b', 'video-a'])
})
