import { flushPromises, shallowMount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, nextTick, type PropType } from 'vue'
import type { Node } from '@vue-flow/core'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import { useWorkbenchStore } from '../store/workbenchStore'
import { loadWorkbenchViewForExport } from '../viewport/workbenchViewportPersistence'
import CreativeCanvas from './CreativeCanvas.vue'

const screen = vi.hoisted(() => ({
  getViewport: vi.fn(() => ({ x: 0, y: 0, zoom: 1 })),
  setViewport: vi.fn(),
  updateNode: vi.fn(),
}))
vi.mock('../runtime/workbenchFlowRuntime', async original => ({
  ...await original<typeof import('../runtime/workbenchFlowRuntime')>(),
  useWorkbenchFlow: () => ({
    ...screen,
    findNode: () => undefined,
    vueFlowRef: { value: { getBoundingClientRect: () => ({ width: 1000, height: 600 }) } },
  }),
}))

const Flow = defineComponent({
  props: { nodes: { type: Array as PropType<Node[]>, required: true } },
  template: '<div/>',
})
async function openCanvas() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useWorkbenchStore()
  store.chapterId = 4
  vi.spyOn(store, 'load').mockResolvedValue()
  vi.spyOn(api, 'workbenchCapabilities').mockRejectedValue(new Error('offline'))
  const wrapper = shallowMount(CreativeCanvas, {
    props: { chapterId: 4, novelId: 1 },
    global: { plugins: [pinia], stubs: { VueFlow: Flow, AppButton: true } },
  })
  await flushPromises()
  return { store, wrapper, flow: wrapper.getComponent(Flow) }
}

afterEach(() => localStorage.clear())

it('tracks a multi-node drag through a graph refresh and commits the final positions once', async () => {
  const { store, wrapper, flow } = await openCanvas()
  const a = store.addNote({ x: 10, y: 20 })
  const b = store.addWatermark({ x: 30, y: 40 })
  store.selectNodes([a.key, b.key])
  await nextTick()
  const nodes = () => flow.props('nodes')
  const nodeData = nodes().find(node => node.id === a.key)!.data
  const move = vi.spyOn(store, 'updateNodeLayout')
  const start = { id: a.key, position: a.position }
  flow.vm.$emit('node-drag-start', { node: start })
  const positions = [
    { id: a.key, position: { x: 150, y: 160 } },
    { id: b.key, position: { x: 170, y: 180 } },
  ]
  const event = { node: positions[0], nodes: positions }
  flow.vm.$emit('node-drag', event)
  store.updateNodeDraft(b.key, { content: 'updated while dragging' })
  await nextTick()
  expect(move).not.toHaveBeenCalled()
  expect(nodes().find(node => node.id === a.key)).toMatchObject(positions[0]!)
  expect(nodes().find(node => node.id === a.key)!.data).toBe(nodeData)
  expect(nodes().find(node => node.id === b.key)!.data.content).toBe('updated while dragging')
  flow.vm.$emit('node-drag-stop', event)
  expect(move).toHaveBeenCalledTimes(2)
  expect(store.nodeByKey(b.key)?.position).toEqual(positions[1]!.position)
  expect(JSON.parse(localStorage.getItem(store.layoutKey())!).nodes[a.key].position).toEqual(positions[0]!.position)
  expect(store.undo()).toBe(true)
  expect(store.nodeByKey(a.key)?.position).toEqual({ x: 10, y: 20 })
  expect(store.redo()).toBe(true)
  expect(store.nodeByKey(a.key)?.position).toEqual(positions[0]!.position)
  wrapper.unmount()
})

it('previews section members in Vue Flow and commits the final group delta once per node', async () => {
  const { store, wrapper, flow } = await openCanvas()
  const member = store.addNote({ x: 40, y: 60 })
  const section = store.addSection([member.key], { x: 10, y: 20 }, { width: 600, height: 400 }, '#31558f')
  const outside = store.addWatermark({ x: 1500, y: 600 })
  const move = vi.spyOn(store, 'updateNodeLayout')
  const save = vi.spyOn(store, 'persistLayout')
  const event = (x: number, y: number) => ({ node: { id: section.key, position: { x, y } } })
  flow.vm.$emit('node-drag-start', event(10, 20))
  flow.vm.$emit('node-drag', event(30, 40))
  expect(screen.updateNode).toHaveBeenLastCalledWith(member.key, { position: { x: 60, y: 80 } })
  store.updateNodeDraft(member.key, { content: 'updated while moving' })
  await nextTick()
  expect(flow.props('nodes').find(n => n.id === member.key)?.position).toEqual({ x: 60, y: 80 })
  expect(move).not.toHaveBeenCalled()
  expect(save).not.toHaveBeenCalled()
  const stop = event(50, 90)
  flow.vm.$emit('node-drag-stop', { ...stop, nodes: [stop.node, { id: member.key, position: { x: 60, y: 80 } }] })
  expect(move).toHaveBeenCalledTimes(2)
  expect(save).toHaveBeenCalledOnce()
  const positions = () => [section.key, member.key, outside.key].map(key => store.nodeByKey(key)?.position)
  expect(positions()).toEqual([{ x: 50, y: 90 }, { x: 80, y: 130 }, { x: 1500, y: 600 }])
  expect(JSON.parse(localStorage.getItem(store.layoutKey())!).nodes[member.key].position).toEqual({ x: 80, y: 130 })
  expect(store.undo()).toBe(true)
  expect(positions()).toEqual([{ x: 10, y: 20 }, { x: 40, y: 60 }, { x: 1500, y: 600 }])
  expect(store.redo()).toBe(true)
  expect(positions()[1]).toEqual({ x: 80, y: 130 })
  wrapper.unmount()
})

it('previews section membership at the live position and applies it when dropped', async () => {
  const { store, wrapper, flow } = await openCanvas()
  const note = store.addNote({ x: 32, y: 40 })
  const section = store.addSection([], { x: 600, y: 400 }, { width: 600, height: 400 }, '#31558f')
  flow.vm.$emit('node-drag-start', { node: { id: note.key, position: note.position } })
  const event = { node: { id: note.key, position: { x: 640, y: 440 } } }
  flow.vm.$emit('node-drag', event)
  await nextTick()
  expect(flow.props('nodes').find(node => node.id === section.key)?.data.drop_candidate).toBe(true)
  expect(store.nodeByKey(note.key)?.position).toEqual({ x: 32, y: 40 })
  flow.vm.$emit('node-drag-stop', event)
  expect(store.nodeByKey(section.key)?.data.node_keys).toEqual([note.key])
  wrapper.unmount()
})

it('restores the exported framing at a new size and saves later viewport moves independently', async () => {
  const { store, wrapper, flow } = await openCanvas()
  const imported = {
    version: 2, viewport: { x: -50, y: -40, zoom: 1 }, canvasSize: { width: 800, height: 400 },
    nodes: {}, manualNodes: [], manualEdges: [],
  }
  store.addNote({ x: 10, y: 20 })
  localStorage.clear()
  store.loadSavedLayout(imported)
  flow.vm.$emit('nodes-initialized')
  await flushPromises()
  expect(screen.setViewport).toHaveBeenCalledWith({ x: 50, y: 60, zoom: 1 })
  screen.getViewport.mockReturnValue({ x: -240, y: 40, zoom: 0.5 })
  flow.vm.$emit('move-end')
  expect(localStorage.getItem(store.layoutKey())).toBeNull()
  expect(loadWorkbenchViewForExport('4')).toEqual({ canvasSize: { width: 1000, height: 600 }, viewport: store.viewport })
  wrapper.unmount()
})
