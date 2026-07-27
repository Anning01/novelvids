import { createPinia, setActivePinia } from 'pinia'
import { expect, it, vi } from 'vitest'
import { api } from '@/api'
import type { Chapter, SingleResponse, WorkbenchBootstrap } from '@/types'
import { useWorkbenchStore } from './workbenchStore'

vi.mock('@/api', () => ({
  api: {
    workbenchBootstrap: vi.fn(),
    enums: vi.fn().mockResolvedValue({ data: { video_model_type: [] } }),
  },
  sleep: vi.fn(),
}))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

function chapter(id: number, name: string): Chapter {
  return {
    id,
    novel_id: 9,
    number: id,
    name,
    created_at: '2026-07-25T00:00:00.000Z',
    updated_at: '2026-07-25T00:00:00.000Z',
  }
}

it('ignores a chapter load that resolves after a newer load', async () => {
  setActivePinia(createPinia())
  const store = useWorkbenchStore()
  const first = deferred<SingleResponse<WorkbenchBootstrap>>()
  const second = deferred<SingleResponse<WorkbenchBootstrap>>()
  vi.mocked(api.workbenchBootstrap)
    .mockReturnValueOnce(first.promise)
    .mockReturnValueOnce(second.promise)

  const loadingFirst = store.load(9, 1)
  const loadingSecond = store.load(9, 2)
  second.resolve({ code: 0, message: 'ok', data: { chapter: chapter(2, '第二章'), assets: [], scenes: [], videos: {} } })
  await loadingSecond
  first.resolve({ code: 0, message: 'ok', data: { chapter: chapter(1, '第一章'), assets: [], scenes: [], videos: {} } })
  await loadingFirst

  expect(store.chapter?.id).toBe(2)
  expect(store.nodes[0]?.title).toContain('第二章')
  expect(store.chapterId).toBe(2)
})

it('aborts owned work without erasing successful canvas nodes', () => {
  setActivePinia(createPinia())
  const store = useWorkbenchStore()
  store.nodes = [{
    id: -1,
    key: 'note-1',
    kind: 'note',
    backendKind: 'note',
    title: '保留节点',
    position: { x: 0, y: 0 },
    size: null,
    zIndex: 1,
    activeVersionId: null,
    status: 'ready',
    data: { ui: {} },
    createdAt: '',
    updatedAt: '',
  }]
  store.busyAssetIds = [1]
  store.busySceneIds = [2]
  const controller = store.beginPendingWork()

  store.cancelPendingWork()

  expect(controller.signal.aborted).toBe(true)
  expect(store.pendingControllers).toEqual([])
  expect(store.busyAssetIds).toEqual([])
  expect(store.busySceneIds).toEqual([])
  expect(store.nodes.map(node => node.key)).toEqual(['note-1'])
})
