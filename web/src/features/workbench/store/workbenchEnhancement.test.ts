import { beforeEach, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useWorkbenchStore } from './workbenchStore'
import { parseWorkbenchState } from './workbenchPersistence'
import { orderedComposerInputs, chapterComposerDisabledReason } from '../config/composerConfig'

beforeEach(() => { setActivePinia(createPinia()); localStorage.clear() })

it('persists a directly connected video card, target, receipt, and result without a converter node', () => {
  const store = useWorkbenchStore(); store.chapterId = 12
  const original = store.addVideoEnhancement({ x: 1, y: 2 })
  const hd = store.addVideoEnhancement({ x: 600, y: 2 })
  expect(store.connectMediaNode(original.key, hd.key, { sourceHandle: 'output-output', targetHandle: 'video-input' })).toBe(true)
  expect(store.connectMediaNode(original.key, hd.key, { sourceHandle: 'output-output', targetHandle: 'video-input' })).toBe(false)
  store.updateManualNodeData(hd.key, { resolution: '2k', export_id: 8, enhancement_result: { id: 8, status: 6 } })
  store.persistLayout()
  const saved = parseWorkbenchState(localStorage.getItem(store.layoutKey())!)!
  expect(saved.manualNodes).toHaveLength(2)
  expect(saved.manualEdges).toHaveLength(1)
  expect(saved.manualNodes.find(item => item.key === hd.key)!.data).toMatchObject({ resolution: '2k', export_id: 8 })
  expect(saved.manualNodes.every(item => item.kind === 'video_enhancement')).toBe(true)
  const other = store.addVideoEnhancement({ x: 1, y: 500 })
  expect(store.connectMediaNode(other.key, hd.key)).toBe(false)
})

it('allows undoing card creation and its input connection independently', () => {
  const store = useWorkbenchStore(); store.chapterId = 12
  const original = store.addVideoEnhancement({ x: 1, y: 2 })
  const hd = store.addVideoEnhancement({ x: 600, y: 2 })
  store.connectMediaNode(original.key, hd.key)
  expect(store.undo()).toBe(true); expect(store.edges).toHaveLength(0)
  expect(store.undo()).toBe(true); expect(store.nodes.map(item => item.key)).toEqual([original.key])
})

it('connects a completed HD video to existing video inputs without pretending chapter composition supports it', () => {
  const store = useWorkbenchStore(); store.chapterId = 12
  const hd = store.addVideoEnhancement({ x: 1, y: 2 })
  store.updateManualNodeData(hd.key, { enhancement_result: { status: 3, url: '/api/video/exports/8/download', output_probe: { duration: 7 } } })
  const composer = store.addVideoComposer()
  expect(store.connectMediaNode(hd.key, composer.key, { sourceHandle: 'output-output', targetHandle: 'video-input' })).toBe(true)
  expect(orderedComposerInputs(composer.key, store.nodes, store.edges)[0]).toMatchObject({ url: '/api/video/exports/8/download', durationSeconds: 7 })
  expect(chapterComposerDisabledReason(composer.key, store.nodes, store.edges)).not.toBe('')
})

it('freezes submitted parameters and input connection while permitting result refresh and a new card', () => {
  const store = useWorkbenchStore(); store.chapterId = 12
  const original = store.addVideoEnhancement({ x: 1, y: 2 })
  const hd = store.addVideoEnhancement({ x: 600, y: 2 })
  store.connectMediaNode(original.key, hd.key)
  const connection = store.edges[0]!
  store.updateManualNodeData(hd.key, { export_id: 8, resolution: '2k', model_id: 12 })
  store.updateManualNodeData(hd.key, { resolution: '4k' })
  store.updateManualNodeData(hd.key, { model_id: 13 })
  store.updateManualNodeData(hd.key, { export_id: null })
  expect(hd.data).toMatchObject({ export_id: 8, resolution: '2k', model_id: 12 })
  expect(store.deleteMediaEdge(connection.key)).toBe(false)
  expect(store.edges).toHaveLength(1)
  store.updateManualNodeData(hd.key, { enhancement_result: { id: 8, status: 3 } })
  expect(hd.data.enhancement_result).toMatchObject({ id: 8, status: 3 })
  const another = store.addVideoEnhancement({ x: 600, y: 500 })
  expect(store.connectMediaNode(original.key, another.key)).toBe(true)
  expect(another.data.export_id).toBeUndefined()
})

it('cannot use undo or redo to change a submitted target or detach its source', () => {
  const store = useWorkbenchStore(); store.chapterId = 12
  const original = store.addVideoEnhancement({ x: 1, y: 2 })
  const hd = store.addVideoEnhancement({ x: 600, y: 2 })
  store.connectMediaNode(original.key, hd.key)
  store.checkpoint()
  store.updateManualNodeData(hd.key, { export_id: 8, resolution: '2k', model_id: 12 })
  expect(store.undo()).toBe(true)
  expect(store.nodeByKey(hd.key)!.data).toMatchObject({ export_id: 8, resolution: '2k', model_id: 12 })
  expect(store.undo()).toBe(true)
  expect(store.mediaEdges.some(item => item.target === hd.key)).toBe(true)
  expect(store.redo()).toBe(true)
  expect(store.nodeByKey(hd.key)!.data).toMatchObject({ export_id: 8, resolution: '2k' })
})


it('allows deleting a locked canvas card without deleting or regenerating the stored video', async () => {
  const store = useWorkbenchStore(); store.chapterId = 12
  const hd = store.addVideoEnhancement({ x: 600, y: 2 })
  store.updateManualNodeData(hd.key, { export_id: 8, resolution: '2k', enhancement_result: { id: 8, status: 3 } })
  await expect(store.deleteNodeKeys([hd.key])).resolves.toBe(1)
  expect(store.nodeByKey(hd.key)).toBeUndefined()
  expect(store.undo()).toBe(true)
  expect(store.nodeByKey(hd.key)!.data).toMatchObject({ export_id: 8, resolution: '2k' })
})
