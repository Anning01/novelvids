import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import StoryboardSheetCard from './StoryboardSheetCard.vue'
import { api } from '@/api'
import type { Scene } from '@/types'
vi.mock('@/api', () => ({api: {generateStoryboardSheet: vi.fn(), task: vi.fn(), scene: vi.fn()}, mediaUrl: (url: string) => url, sleep: vi.fn()}))
const scene: Scene = {id: 3, sequence: 1, prompt: '已确认视频稿', created_at: '', updated_at: ''}
beforeEach(() => vi.clearAllMocks())
it('displays a generated image without replacing the video prompt', async () => {
  vi.mocked(api.generateStoryboardSheet).mockResolvedValue({code: 0, message: '', data: {id: 'job', task_type: 2, status: 1, created_at: ''}})
  vi.mocked(api.task).mockResolvedValue({code: 0, message: '', data: {id: 'job', task_type: 2, status: 3, response_data: {saved: true}, created_at: ''}})
  const saved = {...scene, metadata: {storyboard_sheet: {status: 'completed', image_url: '/media/board.png'}}}
  vi.mocked(api.scene).mockResolvedValue({code: 0, message: '', data: saved})
  const wrapper = mount(StoryboardSheetCard, {props: {scene, enabled: true}})
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(wrapper.emitted('updated')?.[0]).toEqual([saved])
  expect(saved.prompt).toBe(scene.prompt)
  await wrapper.setProps({scene: saved})
  expect(wrapper.get('button').attributes('aria-label')).toBe('重新生成故事版')
  wrapper.unmount()
})
it('recovers an active task after reload and exposes failure without retrying', async () => {
  vi.mocked(api.task).mockResolvedValue({code: 0, message: '', data: {id: 'job', task_type: 2, status: 4, error_message: '图片未返回', created_at: ''}})
  const wrapper = mount(StoryboardSheetCard, {props: {scene: {...scene, metadata: {storyboard_sheet: {task_id: 'job', status: 'pending'}}}, enabled: true}})
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('图片未返回')
  expect(api.generateStoryboardSheet).not.toHaveBeenCalled()
  wrapper.unmount()
})
it('can restore an excluded reference without regenerating when generation is disabled', async () => {
  const wrapper = mount(StoryboardSheetCard, {props: {scene: {...scene, metadata: {storyboard_sheet: {image_url: '/media/old.png'}}}, enabled: false}})
  expect(wrapper.find('button').exists()).toBe(false)
  expect(wrapper.find('img').exists()).toBe(false)
  await wrapper.setProps({canUse: true})
  await wrapper.get('button').trigger('click')
  expect(wrapper.emitted('use')).toHaveLength(1)
  wrapper.unmount()
})
