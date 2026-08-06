import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { useWorkbenchStore } from '../store/workbenchStore'
import VideoComposerNode from './VideoComposerNode.vue'

vi.mock('@/api', () => ({
  api: {},
  sleep: vi.fn(),
}))

const common = {
  id: 'composer-1',
  type: 'video_composer',
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
    key: 'video-a',
    kind: 'video_media',
    backendKind: 'video_media',
    title: '片段 A',
    position: { x: 0, y: 0 },
    size: null,
    zIndex: 1,
    activeVersionId: null,
    status: 'ready',
    data: { url: '/a.mp4', durationSeconds: 4 },
    createdAt: '',
    updatedAt: '',
  }, {
    id: -2,
    key: 'video-b',
    kind: 'video_media',
    backendKind: 'video_media',
    title: '片段 B',
    position: { x: 0, y: 0 },
    size: null,
    zIndex: 1,
    activeVersionId: null,
    status: 'ready',
    data: { url: '/b.mp4', durationSeconds: 6 },
    createdAt: '',
    updatedAt: '',
  }, {
    id: -3,
    key: 'composer-1',
    kind: 'video_composer',
    backendKind: 'video_composer',
    title: '视频合成器',
    position: { x: 400, y: 0 },
    size: null,
    zIndex: 1,
    activeVersionId: null,
    status: 'ready',
    data: { config: { name: '成片 1', resolution: '720p', aspectRatio: '9:16' }, ui: {} },
    createdAt: '',
    updatedAt: '',
  }]
  store.mediaEdges = store.edges = ['video-a', 'video-b'].map((source, index) => ({
    id: -10 - index,
    key: `${source}-composer-1`,
    source,
    target: 'composer-1',
    type: 'output_binding',
    backendType: 'output_binding',
    sourceHandle: 'output',
    targetHandle: 'video-input',
    orderIndex: index,
    config: null,
    createdAt: '',
    updatedAt: '',
  }))
})

function mountNode() {
  return mount(VideoComposerNode, {
    props: {
      ...common,
      data: {
        title: '视频合成器',
        config: { name: '成片 1', resolution: '720p', aspectRatio: '9:16' },
        compose_capability: false,
      },
    } as never,
    global: { stubs: { WorkbenchNodeFrame: frameStub } },
  })
}

it('renders reference inputs, options, and truthful disabled reason', async () => {
  const wrapper = mountNode()

  expect(wrapper.get('[aria-label="成片输入顺序"]').findAll('strong').map(item => item.text())).toEqual(['片段 A', '片段 B'])
  await wrapper.get('[aria-label="分辨率"]').trigger('click')
  expect(wrapper.get('[aria-label="分辨率选项"]').findAll('[role="option"]').map(item => item.text())).toEqual(['480p', '720p', '1080p', '4k'])
  await wrapper.get('[aria-label="分辨率"]').trigger('click')
  await wrapper.get('[aria-label="画面比例"]').trigger('click')
  expect(wrapper.get('[aria-label="画面比例选项"]').findAll('[role="option"]').map(item => item.text())).toEqual(['16:9', '4:3', '1:1', '3:4', '9:16', '21:9'])
  expect(wrapper.get('[aria-label="合成并预览"]').attributes('disabled')).toBeDefined()
  expect(wrapper.get('[role="alert"]').text()).toBe('当前服务未启用视频合成')
})

it('moves clips with the exact reference controls', async () => {
  const wrapper = mountNode()

  await wrapper.get('[aria-label="将 片段 B 上移"]').trigger('click')

  expect(wrapper.get('[aria-label="成片输入顺序"]').findAll('strong').map(item => item.text())).toEqual(['片段 B', '片段 A'])
  expect(store.edges.sort((a, b) => a.orderIndex - b.orderIndex).map(edge => edge.source)).toEqual(['video-b', 'video-a'])
})
