import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { useWorkbenchStore } from './workbenchStore'

vi.mock('@/api', () => ({
  api: {},
  sleep: vi.fn(),
}))

let store: ReturnType<typeof useWorkbenchStore>

beforeEach(() => {
  setActivePinia(createPinia())
  store = useWorkbenchStore()
  store.chapterId = 2162
  localStorage.clear()
})

it('adds a selected persistent watermark node at the requested position', () => {
  vi.spyOn(Date, 'now').mockReturnValueOnce(3001)

  const created = store.addWatermark({ x: 120, y: 240 })

  expect(created).toMatchObject({
    key: 'watermark-3001',
    kind: 'watermark',
    title: '新水印',
    position: { x: 120, y: 240 },
    size: { width: 360, height: 300 },
  })
  expect(created.data.config).toEqual({
    resourceUrl: '',
    x: 0.86,
    y: 0.86,
    scale: 0.2,
  })
  expect(store.selectedNodeKeys).toEqual(['watermark-3001'])
  expect(JSON.parse(localStorage.getItem(store.layoutKey()) || '{}').manualNodes[0].kind).toBe('watermark')
})

it('saves watermark configuration through undo and redo', () => {
  vi.spyOn(Date, 'now').mockReturnValueOnce(3002)
  const created = store.addWatermark({ x: 20, y: 30 })

  store.saveWatermarkConfig(created.key, {
    resourceUrl: '/media/logo.png',
    x: 0.14,
    y: 0.14,
    scale: 0.35,
  })
  expect(store.nodeByKey(created.key)?.data.config).toMatchObject({ x: 0.14, y: 0.14, scale: 0.35 })

  expect(store.undo()).toBe(true)
  expect(store.nodeByKey(created.key)?.data.config).toMatchObject({ x: 0.86, y: 0.86, scale: 0.2 })

  expect(store.redo()).toBe(true)
  expect(store.nodeByKey(created.key)?.data.config).toMatchObject({ x: 0.14, y: 0.14, scale: 0.35 })
})

it.each(['video_media', 'video_result'] as const)('connects %s to the watermark video input', (kind) => {
  vi.spyOn(Date, 'now')
    .mockReturnValueOnce(3100)
    .mockReturnValueOnce(3101)
  const created = store.addWatermark({ x: 400, y: 200 })
  store.nodes.push({
    id: -1,
    key: `source-${kind}`,
    kind,
    backendKind: kind,
    title: '视频来源',
    position: { x: 0, y: 0 },
    size: null,
    zIndex: 1,
    activeVersionId: null,
    status: 'ready',
    data: {},
    createdAt: '',
    updatedAt: '',
  })

  store.connectMediaNode(`source-${kind}`, created.key)

  expect(store.edges.at(-1)).toMatchObject({
    source: `source-${kind}`,
    target: created.key,
    type: 'output_binding',
    sourceHandle: 'output',
    targetHandle: 'video-input',
  })
})
