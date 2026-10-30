import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import { useAuthStore } from '@/features/auth/authStore'
import { downloadFile } from '@/shared/downloadFile'
import { notice } from '@/shared/notice'
import type { Video } from '@/types'
import VideoLastFrameButton from './VideoLastFrameButton.vue'

vi.mock('@/api', async importOriginal => {
  const original = await importOriginal<typeof import('@/api')>()
  return { ...original, api: { ...original.api, extractVideoLastFrame: vi.fn(), generateVideo: vi.fn() } }
})
vi.mock('@/shared/downloadFile', () => ({ downloadFile: vi.fn() }))
vi.mock('@/shared/notice', () => ({ notice: { success: vi.fn(), error: vi.fn() } }))
const video: Video = { id: 37, scene_id: 109, status: 3, model_type: 1, url: '/media/existing.mp4', created_at: '', updated_at: '' }
const extracted: Video = { ...video, metadata: { last_frame_source: 'ffmpeg', last_frame_url: '/media/tail.png', last_frame_injected_scene_id: 110 } }
beforeEach(() => vi.clearAllMocks())
afterEach(() => { delete document.documentElement.dataset.appTheme })

it.each(['light', 'dark'])('extracts without regenerating, then offers download in %s mode', async theme => {
  document.documentElement.dataset.appTheme = theme
  let finish: (value: { data: Video }) => void = () => {}
  vi.mocked(api.extractVideoLastFrame).mockImplementation(() => new Promise(resolve => { finish = resolve as typeof finish }))
  const wrapper = mount(VideoLastFrameButton, { props: { video }, global: { plugins: [createPinia()] } })
  await wrapper.get('button').trigger('click')
  expect(wrapper.get('button').attributes('disabled')).toBeDefined()
  expect(wrapper.get('button').attributes('aria-busy')).toBe('true')
  await wrapper.get('button').trigger('click')
  expect(api.extractVideoLastFrame).toHaveBeenCalledTimes(1)
  finish({ data: extracted }); await flushPromises()
  expect(wrapper.emitted('extracted')?.[0]).toEqual([extracted])
  await wrapper.setProps({ video: extracted })
  expect(wrapper.text()).toContain('下载尾帧')
  await wrapper.get('button').trigger('click'); await flushPromises()
  expect(downloadFile).toHaveBeenCalledWith('/media/tail.png', 'last-frame-37.png')
  expect(api.extractVideoLastFrame).toHaveBeenCalledTimes(1)
  expect(api.generateVideo).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('preserves the video and allows retry after extraction fails; an input tail is not an output', async () => {
  vi.mocked(api.extractVideoLastFrame).mockRejectedValueOnce(new Error('文件暂时不可读取')).mockResolvedValue({ data: extracted } as never)
  const wrapper = mount(VideoLastFrameButton, { props: { video: { ...video, metadata: { last_frame_url: '/media/input.png' } } }, global: { plugins: [createPinia()] } })
  await wrapper.get('button').trigger('click'); await flushPromises()
  expect(notice.error).toHaveBeenCalledWith('文件暂时不可读取')
  expect(wrapper.emitted('extracted')).toBeUndefined()
  expect(wrapper.get('button').attributes('disabled')).toBeUndefined()
  await wrapper.get('button').trigger('click'); await flushPromises()
  expect(wrapper.emitted('extracted')).toHaveLength(1)
  expect(downloadFile).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('does not offer extraction to viewers or for incomplete videos', async () => {
  const pinia = createPinia()
  const wrapper = mount(VideoLastFrameButton, { props: { video: { ...video, status: 2 } }, global: { plugins: [pinia] } })
  expect(wrapper.find('button').exists()).toBe(false)
  const auth = useAuthStore(pinia)
  auth.$patch({ enabled: true, user: { id: 1, username: 'viewer', nickname: '', avatar_url: '', is_super_admin: false }, activeTeamId: 1,
    memberships: [{ team_id: 1, team_name: 'Team', role: 'viewer' }] })
  await wrapper.setProps({ video })
  expect(wrapper.find('button').exists()).toBe(false)
  await wrapper.setProps({ video: extracted })
  expect(wrapper.text()).toContain('下载尾帧')
  wrapper.unmount()
})
