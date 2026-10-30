import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { api, ApiRequestError } from '@/api'
import ShortDramaStoryboardPage from './ShortDramaStoryboardPage.vue'

vi.mock('@/api', async importOriginal => {
  const original = await importOriginal<typeof import('@/api')>()
  return { ...original, api: { ...original.api, novelMeta: vi.fn(), chapters: vi.fn(),
    videoGenerationModels: vi.fn(), workbenchBootstrap: vi.fn(), queryVideo: vi.fn(), generateVideo: vi.fn(),
    extractVideoLastFrame: vi.fn(), videoGenerationHistory: vi.fn(), scene: vi.fn() } }
})

const chapter = { id: 450, novel_id: 9, number: 1, name: '第一章', content: '', created_at: '', updated_at: '' }
const scene = { id: 109, chapter_id: 450, sequence: 1, description: '等待后台结果', prompt: '人物向前走',
  duration: 6, metadata: { current_video_id: 37 }, created_at: '', updated_at: '' }
const pending = { id: 37, scene_id: 109, status: 2, model_type: 1, url: null, metadata: {}, created_at: '', updated_at: '' }
const completed = { ...pending, status: 3, url: '/media/finished.mp4' }
const wrappers: ReturnType<typeof mount>[] = []

beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks(); sessionStorage.clear()
  vi.mocked(api.novelMeta).mockResolvedValue({ data: { id: 9, name: '状态回归', author: 'Agent 创建', created_at: '', updated_at: '' } } as never)
  vi.mocked(api.chapters).mockResolvedValue({ data: { items: [chapter], pagination: { page: 1, pages: 1 } } } as never)
  vi.mocked(api.videoGenerationModels).mockResolvedValue({ data: [] } as never)
  vi.mocked(api.workbenchBootstrap).mockResolvedValue({ data: { chapter, scenes: [structuredClone(scene)], assets: [], videos: { 109: [pending] } } } as never)
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.useRealTimers(); vi.restoreAllMocks(); delete document.documentElement.dataset.appTheme })

async function render() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/create/short-drama/storyboard/:projectId', component: ShortDramaStoryboardPage },
  ] })
  await router.push('/create/short-drama/storyboard/9?chapter=450'); await router.isReady()
  const wrapper = mount(ShortDramaStoryboardPage, { global: { plugins: [createPinia(), router], stubs: {
    ShortDramaWorkspaceShell: { template: '<div><slot name="header-end" /><slot /></div>' },
    DeferredVideoPlayer: { props: ['src'], template: '<video data-testid="preview" :src="src" />' },
  } } })
  wrappers.push(wrapper); await flushPromises()
  return { wrapper, router }
}

it('resumes an existing task and displays a background completion without refreshing or generating', async () => {
  vi.mocked(api.queryVideo).mockResolvedValue({ data: completed } as never)
  const { wrapper } = await render()
  expect(api.queryVideo).toHaveBeenCalled()
  expect(wrapper.get('[data-testid="preview"]').attributes('src')).toBe('/media/finished.mp4')
  expect(wrapper.find('.preview-empty.is-running').exists()).toBe(false)
  expect(api.generateVideo).not.toHaveBeenCalled()
})

it('extracts an existing video tail and updates the next shot reference without refreshing or generating', async () => {
  const nextScene = { ...scene, id: 110, sequence: 2, prompt: '保留下一镜头的画面', metadata: {} }
  vi.mocked(api.workbenchBootstrap).mockResolvedValue({ data: { chapter, scenes: [structuredClone(scene), nextScene], assets: [], videos: { 109: [completed] } } } as never)
  vi.mocked(api.extractVideoLastFrame).mockResolvedValue({ data: { ...completed, metadata: {
    last_frame_url: '/media/tail.png', last_frame_source: 'ffmpeg', last_frame_injected_scene_id: 110,
    last_frame_reference: { type: 'image', url: '/media/tail.png', name: '本镜头尾帧.png' },
    last_frame_prompt_instruction: '【首帧衔接】\n首帧参考：@{参考图片:/media/tail.png}',
  } } } as never)
  const { wrapper } = await render()
  const trigger = wrapper.findAll('button').find(button => button.text().includes('提取尾帧'))!
  await trigger.trigger('click'); await flushPromises()
  expect(api.extractVideoLastFrame).toHaveBeenCalledWith(37)
  expect(wrapper.text()).toContain('下载尾帧')
  expect(wrapper.text()).toContain('保留下一镜头的画面')
  expect(wrapper.text()).toContain('首帧衔接')
  expect(wrapper.find('img[src="/media/tail.png"]').exists()).toBe(true)
  expect(api.generateVideo).not.toHaveBeenCalled()
})

it.each(['light', 'dark'])('reconnects after a temporary failure and replaces the spinner in %s mode', async theme => {
  document.documentElement.dataset.appTheme = theme
  vi.mocked(api.queryVideo).mockRejectedValueOnce(new TypeError('Failed to fetch')).mockResolvedValue({ data: completed } as never)
  const { wrapper } = await render()
  expect(wrapper.text()).toContain('正在重新同步')
  await vi.advanceTimersByTimeAsync(4000); await flushPromises()
  expect(wrapper.get('[data-testid="preview"]').attributes('src')).toBe('/media/finished.mp4')
  expect(wrapper.text()).not.toContain('正在重新同步')
  expect(api.generateVideo).not.toHaveBeenCalled()
})

it('synchronizes immediately on window focus and stops requests after unmount', async () => {
  vi.mocked(api.queryVideo).mockResolvedValueOnce({ data: pending } as never).mockResolvedValue({ data: completed } as never)
  const { wrapper } = await render()
  window.dispatchEvent(new Event('focus')); await flushPromises()
  expect(wrapper.get('[data-testid="preview"]').attributes('src')).toBe('/media/finished.mp4')
  const calls = vi.mocked(api.queryVideo).mock.calls.length
  wrapper.unmount()
  await vi.advanceTimersByTimeAsync(60000)
  window.dispatchEvent(new Event('focus')); await flushPromises()
  expect(api.queryVideo).toHaveBeenCalledTimes(calls)
})

it('does not let an earlier processing response overwrite a completion obtained on focus', async () => {
  let finishEarlier: (value: unknown) => void = () => {}
  vi.mocked(api.queryVideo).mockImplementationOnce(() => new Promise(resolve => { finishEarlier = resolve as typeof finishEarlier }))
    .mockResolvedValue({ data: completed } as never)
  const { wrapper } = await render()
  window.dispatchEvent(new Event('focus')); await flushPromises()
  expect(wrapper.get('[data-testid="preview"]').attributes('src')).toBe('/media/finished.mp4')
  finishEarlier({ data: pending }); await flushPromises()
  expect(wrapper.get('[data-testid="preview"]').attributes('src')).toBe('/media/finished.mp4')
  await vi.advanceTimersByTimeAsync(8000)
  expect(api.queryVideo).toHaveBeenCalledTimes(2)
})

it('ignores a previous chapter response without resetting another chapter or its prompt', async () => {
  const nextChapter = { ...chapter, id: 451, number: 2, name: '第二章' }
  const nextScene = { ...scene, id: 110, chapter_id: 451, prompt: '第二章独立提示词', metadata: { current_video_id: 39 } }
  vi.mocked(api.chapters).mockResolvedValue({ data: { items: [chapter, nextChapter], pagination: { page: 1, pages: 1 } } } as never)
  vi.mocked(api.workbenchBootstrap).mockResolvedValueOnce({ data: { chapter, scenes: [structuredClone(scene)], assets: [], videos: { 109: [pending] } } } as never)
    .mockResolvedValue({ data: { chapter: nextChapter, scenes: [nextScene], assets: [], videos: { 110: [{ ...completed, id: 39, scene_id: 110, url: '/media/next-chapter.mp4' }] } } } as never)
  let finishEarlier: (value: unknown) => void = () => {}
  vi.mocked(api.queryVideo).mockImplementation(() => new Promise(resolve => { finishEarlier = resolve as typeof finishEarlier }))
  const { wrapper, router } = await render()
  await router.push('/create/short-drama/storyboard/9?chapter=451'); await flushPromises()
  finishEarlier({ data: completed }); await flushPromises()
  expect(wrapper.get('[data-testid="preview"]').attributes('src')).toBe('/media/next-chapter.mp4')
  expect(wrapper.text()).toContain('第二章独立提示词')
})

it.each([401, 403, 404])('does not endlessly retry an unavailable or inaccessible video (%s)', async code => {
  vi.mocked(api.queryVideo).mockRejectedValue(new ApiRequestError('无法读取当前视频', code, 200))
  const { wrapper } = await render()
  expect(wrapper.text()).toContain('无法读取当前视频')
  expect(wrapper.text()).toContain('视频状态暂未同步')
  expect(wrapper.find('.preview-empty.is-running').exists()).toBe(false)
  await vi.advanceTimersByTimeAsync(60000)
  expect(api.queryVideo).toHaveBeenCalledTimes(1)
  expect(api.generateVideo).not.toHaveBeenCalled()
})
