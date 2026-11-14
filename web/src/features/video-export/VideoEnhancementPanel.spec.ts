import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import VideoEnhancementPanel from './VideoEnhancementPanel.vue'
import { exportApi, type ChapterExport } from './api'
import { api } from '@/api'
import { downloadFile } from '@/shared/downloadFile'
import { useAuthStore } from '@/features/auth/authStore'
import { setLocale } from '@/i18n'
import type { Video } from '@/types'
import AppButton from '@/components/AppButton.vue'

vi.mock('@/shared/downloadFile', () => ({ downloadFile: vi.fn() }))
const video: Video = { id: 9, scene_id: 1, model_type: 1, status: 3, url: 'https://media.example/9.mp4',
  metadata: { width: 1344, height: 768, poster_url: 'https://media.example/poster.jpg' }, created_at: '', updated_at: '' }
const source: ChapterExport = { id: 1, source_video_id: 9, chapter_id: 2, parent_export_id: null,
  source_version: 'version', source_sha256: 'source-hash', source_probe: { width: 1344, height: 768, duration: 8, fps: 24 },
  output_probe: {}, source_url: '/api/video/exports/1/download?source=true', url: '/api/video/exports/1/download',
  task_id: 'source-task', status: 3, stage: 'completed', error: null, created_at: '', recipe: {} }
const model = { id: 8, name: 'MediaKit', resolutions: [{ value: '1080p', short_side: 1080 }, { value: '2k', short_side: 1440 }, { value: '4k', short_side: 2160 }],
  supported_resolutions: [{ value: '720p', short_side: 720 }, { value: '1080p', short_side: 1080 }, { value: '2k', short_side: 1440 }, { value: '4k', short_side: 2160 }] }
const quote = { amount: '0.666667', currency: 'CNY', source_sha256: 'source-hash', quote_version: 'quote-version' }
function render(extra = {}) {
  return mount(VideoEnhancementPanel, { props: { video, visible: true, sceneSequence: 12, titleId: 'title', ...extra }, global: { plugins: [createPinia()], components: { AppButton } } })
}
beforeEach(() => {
  setLocale('zh')
  vi.restoreAllMocks()
  vi.spyOn(exportApi, 'listVideo').mockResolvedValue({ data: [source] })
  vi.spyOn(exportApi, 'models').mockResolvedValue({ data: [model] })
  vi.spyOn(exportApi, 'quote').mockResolvedValue({ data: quote })
  vi.spyOn(exportApi, 'prepareVideo').mockResolvedValue({ data: { export_id: 1, task_id: 'source-task', status: 1 } })
  vi.spyOn(exportApi, 'enhance').mockResolvedValue({ data: { export_id: 3, task_id: 'enhance-task', status: 1 } })
  vi.spyOn(api, 'videos').mockResolvedValue({ code: 0, message: '', data: { items: [], pagination: { page: 1, page_size: 100, total: 0, pages: 0 } } })
})
afterEach(() => { vi.useRealTimers() })

it('renders the existing preview immediately while requests are pending without downloading or preparing media', async () => {
  vi.mocked(exportApi.listVideo).mockReturnValue(new Promise(() => {}))
  vi.mocked(exportApi.models).mockReturnValue(new Promise(() => {}))
  const wrapper = render()
  expect(wrapper.get('h2').text()).toBe('视频高清化')
  expect(wrapper.text()).toContain('分镜 12')
  expect(wrapper.getComponent({ name: 'VideoThumbnail' }).props('poster')).toBe('https://media.example/poster.jpg')
  expect(wrapper.find('.enhancement-primary').attributes('disabled')).toBeDefined()
  expect(exportApi.prepareVideo).not.toHaveBeenCalled()
  expect(exportApi.enhance).not.toHaveBeenCalled()
  expect(downloadFile).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('reuses a prepared source, shows configured targets and submits only the displayed quote after confirmation', async () => {
  const wrapper = render()
  await flushPromises()
  expect(exportApi.prepareVideo).not.toHaveBeenCalled()
  expect(wrapper.get('[aria-label="720P"]').attributes('disabled')).toBeDefined()
  expect(wrapper.get('.enhancement-primary').text()).toContain('确认增强到 1080P')
  expect(exportApi.enhance).not.toHaveBeenCalled()
  await wrapper.get('[aria-label="2K"]').trigger('click'); await flushPromises()
  expect(exportApi.quote).toHaveBeenLastCalledWith(1, 8, '2k')
  await wrapper.get('.enhancement-primary').trigger('click')
  await wrapper.get('.enhancement-primary').trigger('click')
  await flushPromises()
  expect(exportApi.enhance).toHaveBeenCalledExactlyOnceWith(1, 8, quote, '2k')
  wrapper.unmount()
})

it('does not let a late quote overwrite the newly selected resolution', async () => {
  let resolveOld: ((value: { data: typeof quote }) => void) | undefined
  vi.mocked(exportApi.quote).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
  const wrapper = render(); await flushPromises()
  await wrapper.get('[aria-label="4K"]').trigger('click'); await flushPromises()
  resolveOld?.({ data: { ...quote, amount: '999', quote_version: 'old' } }); await flushPromises()
  expect(wrapper.get('.enhancement-cost').text()).not.toContain('999')
  await wrapper.get('.enhancement-primary').trigger('click'); await flushPromises()
  expect(exportApi.enhance).toHaveBeenCalledWith(1, 8, quote, '4k')
  wrapper.unmount()
})

it('prepares a new source in the background once and polls history without fetching models or quoting repeatedly', async () => {
  vi.useFakeTimers()
  vi.mocked(exportApi.listVideo).mockResolvedValue({ data: [] })
  const wrapper = render(); await flushPromises()
  expect(exportApi.prepareVideo).toHaveBeenCalledExactlyOnceWith(9)
  vi.mocked(exportApi.listVideo).mockResolvedValue({ data: [{ ...source, status: 2, source_sha256: null, stage: 'preparing' }] })
  await vi.advanceTimersByTimeAsync(5000); await flushPromises()
  expect(exportApi.models).toHaveBeenCalledTimes(1)
  expect(exportApi.prepareVideo).toHaveBeenCalledTimes(1)
  vi.mocked(exportApi.listVideo).mockResolvedValue({ data: [source] })
  await vi.advanceTimersByTimeAsync(5000); await flushPromises()
  expect(exportApi.quote).toHaveBeenCalledTimes(1)
  await wrapper.setProps({ visible: false })
  const calls = vi.mocked(exportApi.listVideo).mock.calls.length
  await vi.advanceTimersByTimeAsync(5000); await flushPromises()
  expect(exportApi.listVideo).toHaveBeenCalledTimes(calls)
  wrapper.unmount()
})

it('keeps tracking a submitted job while hidden and reports the selected HD result once', async () => {
  vi.useFakeTimers()
  const wrapper = render(); await flushPromises()
  await wrapper.get('.enhancement-primary').trigger('click'); await flushPromises()
  await wrapper.setProps({ visible: false })
  const hd = { ...source, id: 3, parent_export_id: 1, status: 3, result_video_id: 12, applied_to_scene: true,
    recipe: { resolution: '1080p' }, output_probe: { width: 1890, height: 1080, duration: 8, fps: 24 } }
  vi.mocked(exportApi.listVideo).mockResolvedValue({ data: [hd, source] })
  vi.mocked(api.videos).mockResolvedValue({ code: 0, message: '', data: { items: [{ ...video, id: 12, url: 'https://media.example/hd.mp4' }], pagination: { page: 1, page_size: 100, total: 1, pages: 1 } } })
  await vi.advanceTimersByTimeAsync(5000); await flushPromises()
  expect(wrapper.emitted('applied')).toEqual([[12]])
  expect(wrapper.text()).toContain('已设为当前视频')
  expect(wrapper.get('.enhancement-primary').text()).toContain('下载高清版')
  expect(exportApi.models).toHaveBeenCalledTimes(1)
  expect(wrapper.getComponent({ name: 'VideoThumbnail' }).props('src')).toBe('https://media.example/hd.mp4')
  wrapper.unmount()
})

it('offers a working retry after a failed response without a manual review flow', async () => {
  vi.mocked(exportApi.enhance).mockRejectedValue(new Error('Network disconnected'))
  const wrapper = render(); await flushPromises()
  await wrapper.get('.enhancement-primary').trigger('click'); await flushPromises()
  expect(wrapper.text()).not.toContain('核对')
  expect(wrapper.get('.enhancement-primary').text()).toBe('重置并重试')
  await wrapper.get('.enhancement-primary').trigger('click'); await flushPromises()
  expect(exportApi.enhance).toHaveBeenCalledTimes(2)
  expect(wrapper.emitted('close')).toBeUndefined()
  wrapper.unmount()
})

it('blocks equal and lower targets for a 1080p video while allowing a configured higher target', async () => {
  vi.mocked(exportApi.listVideo).mockResolvedValue({ data: [{ ...source, source_probe: { ...source.source_probe, width: 1920, height: 1080 } }] })
  const wrapper = render({ video: { ...video, metadata: { width: 1920, height: 1080 } } }); await flushPromises()
  expect(wrapper.get('[aria-label="1080P"]').attributes('disabled')).toBeDefined()
  expect(wrapper.get('[aria-label="2K"]').attributes('aria-checked')).toBe('true')
  expect(exportApi.quote).toHaveBeenLastCalledWith(1, 8, '2k')
  wrapper.unmount()
})

it('does not prepare anything when no service is available or history fails to load', async () => {
  vi.mocked(exportApi.models).mockResolvedValue({ data: [] })
  vi.mocked(exportApi.listVideo).mockResolvedValue({ data: [] })
  const wrapper = render(); await flushPromises()
  expect(wrapper.text()).toContain('尚未配置增强服务')
  expect(exportApi.prepareVideo).not.toHaveBeenCalled()
  wrapper.unmount()
  vi.mocked(exportApi.models).mockResolvedValue({ data: [model] })
  vi.mocked(exportApi.listVideo).mockRejectedValue(new Error('Offline'))
  const failed = render(); await flushPromises()
  expect(failed.text()).toContain('Offline')
  expect(exportApi.prepareVideo).not.toHaveBeenCalled()
  expect(exportApi.enhance).not.toHaveBeenCalled()
  failed.unmount()
})

it('uses the existing read-only permission scope and discards a late response after the role changes', async () => {
  let finish: ((response: { data: ChapterExport[] }) => void) | undefined
  vi.mocked(exportApi.listVideo).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  const wrapper = render()
  const auth = useAuthStore()
  auth.$patch({ enabled: true, user: { id: 1, username: 'viewer', nickname: '', avatar_url: '', is_super_admin: false },
    activeTeamId: 2, memberships: [{ team_id: 2, team_name: 'Other', role: 'viewer' }] })
  await flushPromises()
  finish?.({ data: [{ ...source, source_probe: { width: 10, height: 10, duration: 12345, fps: 1 } }] })
  await flushPromises()
  expect(wrapper.text()).not.toContain('12345')
  expect(wrapper.get('.enhancement-primary').attributes('disabled')).toBeDefined()
  expect(exportApi.quote).not.toHaveBeenCalled()
  expect(exportApi.prepareVideo).not.toHaveBeenCalled()
  expect(exportApi.enhance).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('allows an explicit preparation retry after a read failure without submitting enhancement', async () => {
  vi.mocked(exportApi.listVideo).mockResolvedValue({ data: [] })
  vi.mocked(exportApi.prepareVideo).mockRejectedValueOnce(new Error('Read failed'))
  const wrapper = render(); await flushPromises()
  expect(wrapper.text()).toContain('Read failed')
  await wrapper.get('.enhancement-primary').trigger('click'); await flushPromises()
  expect(exportApi.prepareVideo).toHaveBeenCalledTimes(2)
  expect(exportApi.enhance).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('retries a failed quote as a read operation and never auto-generates media', async () => {
  vi.mocked(exportApi.quote).mockRejectedValueOnce(new Error('Quote offline'))
  const wrapper = render(); await flushPromises()
  expect(wrapper.text()).toContain('Quote offline')
  await wrapper.get('.enhancement-primary').trigger('click'); await flushPromises()
  expect(exportApi.quote).toHaveBeenCalledTimes(2)
  expect(exportApi.enhance).not.toHaveBeenCalled()
  expect(wrapper.get('.enhancement-primary').text()).toContain('确认增强')
  wrapper.unmount()
})

it('uses an existing completed result without enhancing or billing it again', async () => {
  const hd = { ...source, id: 3, parent_export_id: 1, result_video_id: 12, applied_to_scene: false, recipe: { resolution: '1080p' } }
  vi.mocked(exportApi.listVideo).mockResolvedValue({ data: [hd, source] })
  vi.mocked(exportApi.quote).mockResolvedValue({ data: { ...quote, amount: '0', reused_export_id: 3 } })
  const apply = vi.spyOn(exportApi, 'apply').mockResolvedValue({ data: { ...video, id: 12, url: 'https://media.example/hd.mp4' } })
  const wrapper = render(); await flushPromises()
  expect(wrapper.text()).toContain('使用已有结果，不产生新增增强费用')
  await wrapper.get('.enhancement-primary').trigger('click'); await flushPromises()
  expect(apply).toHaveBeenCalledExactlyOnceWith(3)
  expect(wrapper.emitted('applied')).toEqual([[12]])
  expect(exportApi.enhance).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('restores the original through the existing selection API, without generation or billing', async () => {
  vi.mocked(exportApi.listVideo).mockResolvedValueOnce({ data: [{ ...source, id: 3, parent_export_id: 1,
    result_video_id: 12, applied_to_scene: true, recipe: { resolution: '1080p' } }, source] }).mockResolvedValue({ data: [source] })
  const select = vi.spyOn(api, 'selectCurrentVideo').mockResolvedValue({ code: 0, message: '', data: video })
  const wrapper = render(); await flushPromises()
  await wrapper.get('.enhancement-history summary').trigger('click')
  await wrapper.findAll('button').find(button => button.text() === '恢复原视频')!.trigger('click'); await flushPromises()
  expect(select).toHaveBeenCalledExactlyOnceWith(9)
  expect(wrapper.emitted('applied')?.at(-1)).toEqual([9])
  expect(exportApi.enhance).not.toHaveBeenCalled()
  expect(wrapper.text()).not.toContain('已设为当前视频')
  wrapper.unmount()
})

it.each(['light', 'dark'])('keeps provider, unsupported target and failure states in the %s theme', async theme => {
  document.documentElement.dataset.appTheme = theme
  vi.mocked(exportApi.models).mockResolvedValue({ data: [{ ...model, resolutions: [model.resolutions[0]!] }] })
  const wrapper = render(); await flushPromises()
  expect(wrapper.get('[aria-label="4K"]').attributes('disabled')).toBeDefined()
  expect(wrapper.get('[aria-label="4K"]').attributes('title')).toBe('服务未启用')
  vi.mocked(exportApi.listVideo).mockResolvedValue({ data: [{ ...source, id: 3, parent_export_id: 1, status: 4,
    applied_to_scene: true, error: 'Provider failed', recipe: { resolution: '1080p' } }, source] })
  window.dispatchEvent(new Event('focus')); await flushPromises()
  expect(wrapper.text()).toContain('Provider failed')
  expect(wrapper.get('.enhancement-primary').text()).toBe('重置并重试')
  wrapper.unmount(); delete document.documentElement.dataset.appTheme
})

it('blocks unsupported input sizes and keeps the target and fee unavailable', async () => {
  vi.mocked(exportApi.models).mockResolvedValue({ data: [{ ...model, input_short_side_max: 720 }] })
  const wrapper = render(); await flushPromises()
  expect(wrapper.text()).toContain('所选服务不支持当前视频尺寸')
  expect(wrapper.get('.enhancement-primary').attributes('disabled')).toBeDefined()
  expect(exportApi.quote).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('plays the existing video URL on demand and stops playback when the dialog closes', async () => {
  const wrapper = render(); await flushPromises()
  await wrapper.get('.enhancement-play').trigger('click')
  expect(wrapper.get('.enhancement-preview>video').attributes('src')).toBe(video.url)
  expect(downloadFile).not.toHaveBeenCalled()
  await wrapper.setProps({ visible: false })
  expect(wrapper.find('.enhancement-preview>video').exists()).toBe(false)
  expect(exportApi.enhance).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('notifies the page when a previously used HD version is selected again', async () => {
  const hd = { ...source, id: 3, parent_export_id: 1, result_video_id: 12, applied_to_scene: true, recipe: { resolution: '1080p' } }
  vi.mocked(exportApi.listVideo).mockResolvedValueOnce({ data: [hd, source] }).mockResolvedValue({ data: [{ ...hd, applied_to_scene: false }, source] })
  vi.spyOn(api, 'selectCurrentVideo').mockResolvedValue({ code: 0, message: '', data: video })
  vi.spyOn(exportApi, 'apply').mockResolvedValue({ data: { ...video, id: 12 } })
  const wrapper = render(); await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === '恢复原视频')!.trigger('click'); await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === '使用此版本')!.trigger('click'); await flushPromises()
  expect(wrapper.emitted('applied')).toEqual([[12], [9], [12]])
  expect(exportApi.enhance).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('shows download errors even when the enhanced result is completed', async () => {
  vi.mocked(exportApi.listVideo).mockResolvedValue({ data: [{ ...source, id: 3, parent_export_id: 1,
    result_video_id: 12, applied_to_scene: true, recipe: { resolution: '1080p' } }, source] })
  vi.mocked(downloadFile).mockRejectedValueOnce(new Error('Download offline'))
  const wrapper = render(); await flushPromises()
  await wrapper.get('.enhancement-primary').trigger('click'); await flushPromises()
  expect(wrapper.findAll('[role="alert"]').some(alert => alert.text().includes('Download offline'))).toBe(true)
  expect(exportApi.enhance).not.toHaveBeenCalled()
  wrapper.unmount()
})
