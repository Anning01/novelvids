import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { api } from '@/api'
import ShortDramaVideoPage from './ShortDramaVideoPage.vue'

vi.mock('@/api', async importOriginal => {
  const original = await importOriginal<typeof import('@/api')>()
  return { ...original, api: { ...original.api, novelMeta: vi.fn(), chapters: vi.fn(), workbenchBootstrap: vi.fn(), mergeChapterVideos: vi.fn() } }
})
const chapter = { id: 450, novel_id: 9, number: 1, name: '连续播放', created_at: '', updated_at: '' }
const scenes = [1, 2, 3].map(id => ({ id, chapter_id: 450, sequence: id, description: `镜头${id}`, duration: 2, created_at: '', updated_at: '' }))
const videos = Object.fromEntries(scenes.map(scene => [scene.id, [{ id: scene.id, scene_id: scene.id, status: 3,
  model_type: 1, url: `/media/clip-${scene.id}.mp4`, metadata: { duration: 2 }, created_at: '', updated_at: '' }]]))
let paused: WeakMap<HTMLMediaElement, boolean>

beforeEach(() => {
  vi.clearAllMocks()
  paused = new WeakMap()
  vi.spyOn(HTMLMediaElement.prototype, 'paused', 'get').mockImplementation(function (this: HTMLMediaElement) { return paused.get(this) ?? true })
  vi.spyOn(HTMLMediaElement.prototype, 'readyState', 'get').mockReturnValue(4)
  vi.spyOn(HTMLMediaElement.prototype, 'duration', 'get').mockReturnValue(2)
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {})
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(function (this: HTMLMediaElement) { paused.set(this, true); this.dispatchEvent(new Event('pause')) })
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(function (this: HTMLMediaElement) {
    paused.set(this, false); this.dispatchEvent(new Event('play')); this.dispatchEvent(new Event('playing'))
    return Promise.resolve()
  })
  vi.mocked(api.novelMeta).mockResolvedValue({ data: { id: 9, name: '连续预览', created_at: '', updated_at: '' } } as never)
  vi.mocked(api.chapters).mockResolvedValue({ data: { items: [chapter] } } as never)
  vi.mocked(api.workbenchBootstrap).mockResolvedValue({ data: { chapter, scenes, assets: [], videos } } as never)
})
afterEach(() => { vi.restoreAllMocks(); delete document.documentElement.dataset.appTheme })

async function render() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/create/short-drama/video/:projectId', component: ShortDramaVideoPage },
  ] })
  await router.push('/create/short-drama/video/9?chapter=450'); await router.isReady()
  const wrapper = mount(ShortDramaVideoPage, { global: { plugins: [router, createPinia()], stubs: {
    ShortDramaWorkspaceShell: { template: '<div><slot name="header-end" /><slot /></div>' },
    ChapterExportPanel: true, VideoThumbnail: true,
  } } })
  await flushPromises()
  return wrapper
}

it.each(['light', 'dark'])('prebuffers and reuses the next clip instead of mounting a cold player (%s)', async theme => {
  document.documentElement.dataset.appTheme = theme
  const wrapper = await render()
  expect(wrapper.findAll('.video-stage video')).toHaveLength(0)
  await wrapper.get('button[aria-label="播放"]').trigger('click'); await flushPromises()
  const first = wrapper.get('.video-stage video[src="/media/clip-1.mp4"]').element
  const next = wrapper.get('.video-stage video[src="/media/clip-2.mp4"]').element
  expect(next.getAttribute('preload')).toBe('auto')
  first.dispatchEvent(new Event('ended')); await flushPromises()
  expect(wrapper.get('.video-stage video[src="/media/clip-2.mp4"]').element).toBe(next)
  expect(paused.get(next as HTMLMediaElement)).toBe(false)
  expect(wrapper.get('.video-stage-header').text()).toContain('分镜 2')
  expect(wrapper.get('.video-stage video[src="/media/clip-3.mp4"]').element).toBe(first)
  expect(api.mergeChapterVideos).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('preserves black gaps and primes the following real clip while the gap runs', async () => {
  vi.mocked(api.workbenchBootstrap).mockResolvedValue({ data: { chapter, scenes, assets: [], videos: { 1: videos[1], 3: videos[3] } } } as never)
  const wrapper = await render()
  await wrapper.get('button[aria-label="播放"]').trigger('click'); await flushPromises()
  wrapper.get('.video-stage video[src="/media/clip-1.mp4"]').element.dispatchEvent(new Event('ended'))
  await flushPromises()
  expect(wrapper.find('.video-stage-blackout').exists()).toBe(true)
  expect(wrapper.get('.video-stage-header').text()).toContain('分镜 2')
  expect(wrapper.get('.video-stage video[src="/media/clip-3.mp4"]').attributes('preload')).toBe('auto')
  wrapper.unmount()
})
