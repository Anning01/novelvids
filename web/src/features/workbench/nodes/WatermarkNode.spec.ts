import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { useWorkbenchStore } from '../store/workbenchStore'
import WatermarkNode from './WatermarkNode.vue'

vi.mock('@/api', () => ({
  api: { upload: vi.fn() },
  sleep: vi.fn(),
}))

const common = {
  id: 'watermark-1',
  type: 'watermark',
  selected: false,
  dragging: false,
  connectable: true,
  positionAbsoluteX: 0,
  positionAbsoluteY: 0,
  zIndex: 1,
  isValidTargetPos: false,
  isValidSourcePos: false,
}
const frameStub = { template: '<article><slot /></article>' }
let store: ReturnType<typeof useWorkbenchStore>

beforeEach(() => {
  setActivePinia(createPinia())
  store = useWorkbenchStore()
  store.nodes = [{
    id: -1,
    key: 'video-media-1',
    kind: 'video_media',
    backendKind: 'video_media',
    title: '输入视频',
    position: { x: 0, y: 0 },
    size: null,
    zIndex: 1,
    activeVersionId: null,
    status: 'ready',
    data: { url: '/media/input.mp4' },
    createdAt: '',
    updatedAt: '',
  }, {
    id: -2,
    key: 'watermark-1',
    kind: 'watermark',
    backendKind: 'watermark',
    title: '新水印',
    position: { x: 400, y: 0 },
    size: null,
    zIndex: 1,
    activeVersionId: null,
    status: 'ready',
    data: { config: { resourceUrl: '/media/logo.png', x: 0.86, y: 0.86, scale: 0.2 }, ui: {} },
    createdAt: '',
    updatedAt: '',
  }]
  store.edges = [{
    id: -3,
    key: 'edge-1',
    source: 'video-media-1',
    target: 'watermark-1',
    type: 'output_binding',
    backendType: 'output_binding',
    sourceHandle: 'output',
    targetHandle: 'video-input',
    orderIndex: 0,
    config: null,
    createdAt: '',
    updatedAt: '',
  }]
})

it('previews the connected video and watermark image', () => {
  const wrapper = mount(WatermarkNode, {
    props: {
      ...common,
      data: {
        title: '新水印',
        config: { resourceUrl: '/media/logo.png', x: 0.86, y: 0.86, scale: 0.2 },
        apply_capability: false,
      },
    } as never,
    global: { stubs: { WorkbenchNodeFrame: frameStub, Teleport: true } },
  })

  expect(wrapper.get('video').attributes('src')).toBe('/media/input.mp4')
  expect(wrapper.get('img[alt="水印预览图"]').attributes('src')).toBe('/media/logo.png')
  expect(wrapper.get('[aria-label="当前服务未启用水印执行"]').attributes('disabled')).toBeDefined()
})

it('opens reference-style settings and saves changes through the store', async () => {
  const wrapper = mount(WatermarkNode, {
    props: {
      ...common,
      data: {
        title: '新水印',
        config: { resourceUrl: '/media/logo.png', x: 0.86, y: 0.86, scale: 0.2 },
        apply_capability: false,
      },
    } as never,
    global: { stubs: { WorkbenchNodeFrame: frameStub, Teleport: true } },
  })

  await wrapper.get('[aria-label="设置水印"]').trigger('click')
  await wrapper.get('[aria-label="水印位置"]').setValue('center')

  expect(store.nodeByKey('watermark-1')?.data.config).toMatchObject({ x: 0.5, y: 0.5, scale: 0.2 })
})
