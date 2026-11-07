import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import VideoGenerationProgress from './VideoGenerationProgress.vue'
import { TaskStatusEnum, type Video } from '@/types'

const running: Video = { id: 1, scene_id: 9, model_type: 1, status: TaskStatusEnum.PROCESSING,
  created_at: '2026-11-07T12:00:00Z', updated_at: '2026-11-07T12:01:00Z' }
beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(new Date('2026-11-07T12:12:31Z')) })
afterEach(() => { vi.useRealTimers(); delete document.documentElement.dataset.appTheme })

it.each(['light', 'dark'])('shows persistent elapsed time and keeps ticking after remount (%s)', async theme => {
  document.documentElement.dataset.appTheme = theme
  const wrapper = mount(VideoGenerationProgress, { props: { video: running } })
  expect(wrapper.text()).toContain('12 分 31 秒')
  expect(wrapper.text()).toContain('视频生成中')
  await vi.advanceTimersByTimeAsync(2000)
  expect(wrapper.get('time').text()).toBe('12 分 33 秒')
  wrapper.unmount()
  expect(vi.getTimerCount()).toBe(0)
  const restored = mount(VideoGenerationProgress, { props: { video: running } })
  expect(restored.get('time').text()).toBe('12 分 33 秒')
  restored.unmount()
})

it('distinguishes queueing and status sync failure without fabricating a percentage or resetting the clock', async () => {
  const wrapper = mount(VideoGenerationProgress, { props: { video: { ...running, status: TaskStatusEnum.QUEUED } } })
  expect(wrapper.text()).toContain('排队等待生成')
  await wrapper.setProps({ syncDelayed: true })
  expect(wrapper.text()).toContain('视频状态暂未同步')
  expect(wrapper.text()).toContain('不必重新生成')
  expect(wrapper.get('time').text()).toBe('12 分 31 秒')
  expect(wrapper.text()).not.toContain('%')
  wrapper.unmount()
})

it('reports missing timestamps honestly and stops its timer for finished records', async () => {
  const wrapper = mount(VideoGenerationProgress, { props: { video: { ...running, created_at: '' } } })
  expect(wrapper.text()).toContain('正在同步计时信息')
  expect(wrapper.find('time').exists()).toBe(false)
  await wrapper.setProps({ video: { ...running, status: TaskStatusEnum.COMPLETED } })
  expect(vi.getTimerCount()).toBe(0)
  wrapper.unmount()
})
