import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/features/auth/authStore'
import { exportApi, type ChapterExport } from '@/features/video-export/api'
import { appConfirm } from '@/shared/confirmDialog'
import { fetchFileBlob } from '@/shared/downloadFile'
import { useWorkbenchStore } from '../store/workbenchStore'
import type { WorkbenchNode } from '../types/workbenchTypes'
import VideoEnhancementNode from './VideoEnhancementNode.vue'
import WorkbenchSelect from '../components/WorkbenchSelect.vue'

vi.mock('@/shared/confirmDialog', () => ({ appConfirm: vi.fn() }))
vi.mock('@/shared/downloadFile', () => ({ downloadFile: vi.fn(), fetchFileBlob: vi.fn() }))
const source: ChapterExport = { id: 10, chapter_id: 2, parent_export_id: null, source_version: 'a', source_sha256: 'b',
  source_probe: { width: 864, height: 496 }, output_probe: {}, source_url: '/source', url: '/source', task_id: 'source',
  status: 3, stage: 'completed', error: null, created_at: '', recipe: {} }
const output: ChapterExport = { ...source, id: 20, parent_export_id: 10, recipe: { resolution: '2k' },
  output_probe: { width: 2560, height: 1440 }, url: '/api/video/exports/20/download' }
const quote = { amount: '0.833333', currency: 'CNY', source_sha256: 'b', quote_version: 'c' }
let store: ReturnType<typeof useWorkbenchStore>
let pinia: ReturnType<typeof createPinia>
const wrappers: Array<ReturnType<typeof mount>> = []

beforeEach(() => {
  vi.restoreAllMocks()
  pinia = createPinia(); setActivePinia(pinia)
  store = useWorkbenchStore(); store.chapterId = 2
  store.nodes.push({ id: 1, backendKind: 'video_result', position: { x: 0, y: 0 }, size: null, zIndex: 1, activeVersionId: null, status: 'ready', createdAt: '', updatedAt: '', key: 'original', kind: 'video_result', title: '原视频', data: { video: { id: 12, status: 3, url: '/media/source.mp4', metadata: { width: 864, height: 496 } } } } as WorkbenchNode)
  const node = store.addVideoEnhancement({ x: 50, y: 30 })
  store.connectMediaNode('original', node.key, { sourceHandle: 'output-output', targetHandle: 'video-input' })
  vi.spyOn(exportApi, 'models').mockResolvedValue({ data: [{ id: 8, name: 'MediaKit', supported_resolutions: [{ value: '720p', short_side: 720 }, { value: '1080p', short_side: 1080 }, { value: '2k', short_side: 1440 }, { value: '4k', short_side: 2160 }], resolutions: [
    { value: '720p', short_side: 720 }, { value: '1080p', short_side: 1080 }, { value: '2k', short_side: 1440 },
  ] }] })
  vi.spyOn(exportApi, 'prepareVideo').mockResolvedValue({ data: { export_id: 10, task_id: 'source', status: 3 } })
  vi.spyOn(exportApi, 'get').mockImplementation(async id => ({ data: id === 10 ? source : output }))
  vi.spyOn(exportApi, 'quote').mockResolvedValue({ data: quote })
  vi.spyOn(exportApi, 'enhance').mockResolvedValue({ data: { export_id: 20, task_id: 'enhanced', status: 3 } })
  vi.mocked(appConfirm).mockResolvedValue(true)
  vi.mocked(fetchFileBlob).mockResolvedValue(new Blob(['video']))
  vi.stubGlobal('URL', { ...URL, createObjectURL: vi.fn(() => 'blob:enhanced'), revokeObjectURL: vi.fn() })
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.useRealTimers(); vi.unstubAllGlobals() })

async function render() {
  const node = store.nodes.find(item => item.kind === 'video_enhancement')!
  const wrapper = mount(VideoEnhancementNode, { props: { id: node.key, data: node.data, type: node.kind } as never,
    global: { plugins: [pinia], stubs: { WorkbenchNodeFrame: { template: '<article><slot name="meta" /><slot name="toolbar-actions" /><slot /></article>' }, WorkbenchVideoMedia: { props: ['src','running','failed','error'], template: '<div data-media :data-src="src" :data-running="running" :data-failed="failed">{{ error }}</div>' } } } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}

it('creates a directly playable new video using the selected target only after confirmation', async () => {
  const wrapper = await render()
  expect(exportApi.prepareVideo).not.toHaveBeenCalled()
  await wrapper.getComponent(WorkbenchSelect).vm.$emit('update:modelValue', '2k')
  await wrapper.get('.enhanced-video-run').trigger('click'); await flushPromises()
  expect(exportApi.prepareVideo).toHaveBeenCalledWith(12)
  expect(exportApi.quote).toHaveBeenCalledWith(10, 8, '2k')
  expect(appConfirm).toHaveBeenCalledWith(expect.objectContaining({ title: '确认增强到 2K', message: expect.stringContaining('0.833333') }))
  expect(exportApi.enhance).toHaveBeenCalledExactlyOnceWith(10, 8, quote, '2k')
  expect(wrapper.get('[data-media]').attributes('data-src')).toBe('blob:enhanced')
  expect(wrapper.text()).toContain('2560 × 1440')
  expect(store.nodes.find(item => item.kind === 'video_enhancement')!.data.export_id).toBe(20)
  expect(store.nodes[0]!.data.video).toMatchObject({ id: 12, url: '/media/source.mp4' })
  expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
})

it('refreshes the selected storyboard video once when the HD result is applied', async () => {
  store.nodes.find(item => item.kind === 'video_enhancement')!.data.export_id = 20
  vi.mocked(exportApi.get).mockResolvedValue({ data: { ...output, result_video_id: 30, applied_to_scene: true } })
  const refresh = vi.spyOn(store, 'refreshEnhancedVideo').mockResolvedValue()
  vi.useFakeTimers()
  await render()
  expect(refresh).toHaveBeenCalledExactlyOnceWith(30)
  await vi.advanceTimersByTimeAsync(5000); await flushPromises()
  expect(refresh).toHaveBeenCalledOnce()
  expect(exportApi.enhance).not.toHaveBeenCalled()
})

it('does not charge on cancelled confirmation, changed source, or read-only accounts', async () => {
  vi.mocked(appConfirm).mockResolvedValueOnce(false)
  const wrapper = await render()
  await wrapper.get('.enhanced-video-run').trigger('click'); await flushPromises()
  expect(exportApi.enhance).not.toHaveBeenCalled()
  vi.mocked(appConfirm).mockImplementationOnce(async () => { (store.nodes[0]!.data.video as { id: number }).id = 13; return true })
  await wrapper.get('.enhanced-video-run').trigger('click'); await flushPromises()
  expect(exportApi.enhance).not.toHaveBeenCalled()
  const auth = useAuthStore(); auth.enabled = true; auth.activeTeamId = 1; auth.memberships = [{ team_id: 1, role: 'viewer' }] as typeof auth.memberships
  await flushPromises()
  expect(wrapper.get('.enhanced-video-run').attributes('disabled')).toBeDefined()
})

it('disables equal and lower resolutions and permits a higher one for an actual HD input', async () => {
  const input = store.nodes[0]!.data.video as { metadata: unknown }
  input.metadata = { width: 1080, height: 1920 }
  const wrapper = await render()
  expect(wrapper.getComponent(WorkbenchSelect).props('options').map(item => item.disabled)).toEqual([true, true, false, true])
  expect(wrapper.get('.enhanced-video-run').attributes('disabled')).toBeDefined()
  await wrapper.getComponent(WorkbenchSelect).vm.$emit('update:modelValue', '2k')
  expect(wrapper.get('.enhanced-video-run').attributes('disabled')).toBeUndefined()
})

it('resumes a persisted task and polls it without resubmitting or quoting', async () => {
  vi.useFakeTimers()
  const node = store.nodes.find(item => item.kind === 'video_enhancement')!
  node.data.export_id = 20; node.data.resolution = '2k'
  vi.mocked(exportApi.get).mockResolvedValueOnce({ data: { ...output, status: 6, url: null, stage: 'waiting_media' } })
  const wrapper = await render()
  expect(wrapper.get('[data-media]').attributes('data-running')).toBe('true')
  await vi.advanceTimersByTimeAsync(5000); await flushPromises()
  expect(wrapper.get('[data-media]').attributes('data-src')).toBe('blob:enhanced')
  expect(exportApi.quote).not.toHaveBeenCalled(); expect(exportApi.enhance).not.toHaveBeenCalled()
  wrapper.unmount()
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:enhanced')
})

it('shows a persisted failed task without replaying its paid operation', async () => {
  store.nodes.find(item => item.kind === 'video_enhancement')!.data.export_id = 20
  vi.mocked(exportApi.get).mockResolvedValue({ data: { ...output, status: 4, stage: 'needs_review', error: '待核对', url: null } })
  const wrapper = await render()
  expect(wrapper.get('[data-media]').attributes('data-failed')).toBe('true')
  expect(wrapper.text()).toContain('需要核对')
  expect(exportApi.enhance).not.toHaveBeenCalled()
})

it('ignores an old scope response without blocking the current scope result', async () => {
  store.nodes.find(item => item.kind === 'video_enhancement')!.data.export_id = 20
  let resolveOld: (value: { data: ChapterExport }) => void = () => {}
  vi.mocked(exportApi.get).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
  const wrapper = await render()
  store.chapterId = 3
  await flushPromises()
  expect(wrapper.get('[data-media]').attributes('data-src')).toBe('blob:enhanced')
  resolveOld({ data: { ...output, status: 4, url: null, error: 'old scope error' } })
  await flushPromises()
  expect(wrapper.text()).not.toContain('old scope error')
  expect(wrapper.get('[data-media]').attributes('data-src')).toBe('blob:enhanced')
})

it('uses only the video stage and centered actions while exposing unconfigured resolution tiers', async () => {
  useAuthStore().enabled = false
  vi.mocked(exportApi.models).mockResolvedValue({ data: [{ id: 8, name: 'Legacy',
    supported_resolutions: [{ value: '720p', short_side: 720 }, { value: '1080p', short_side: 1080 }, { value: '2k', short_side: 1440 }, { value: '4k', short_side: 2160 }],
    resolutions: [{ value: '1080p', short_side: 1080 }],
  }] })
  const wrapper = await render()
  expect(wrapper.get('article').classes()).toContain('viral-workbench-surface-theme')
  expect(wrapper.find('.enhanced-video-controls').exists()).toBe(false)
  expect(wrapper.find('select').exists()).toBe(false)
  expect(wrapper.text()).not.toContain('来源')
  const picker = wrapper.getComponent(WorkbenchSelect)
  expect(picker.props('options').map(item => [item.label, item.disabled, item.description])).toEqual([
    ['720P', true, '服务未启用'], ['1080P', false, ''], ['2K', true, '服务未启用'], ['4K', true, '服务未启用'],
  ])
  expect(wrapper.get('[aria-label="启用更多清晰度"]').attributes('href')).toBe('#/settings')
  expect(exportApi.enhance).not.toHaveBeenCalled()
})

it('locks the target, service, and execution as soon as submission is saved, before history returns', async () => {
  const node = store.nodes.find(item => item.kind === 'video_enhancement')!
  node.data.export_id = 20
  vi.mocked(exportApi.get).mockImplementationOnce(() => new Promise(() => {}))
  const wrapper = await render()
  expect(wrapper.findComponent(WorkbenchSelect).exists()).toBe(false)
  expect(wrapper.find('.enhanced-video-run').exists()).toBe(false)
  expect(exportApi.prepareVideo).not.toHaveBeenCalled()
  expect(exportApi.enhance).not.toHaveBeenCalled()
})
