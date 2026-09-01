import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import RemakeSourceNode from './RemakeSourceNode.vue'

vi.mock('@/api', () => ({ api: {}, mediaUrl: (value: string) => value, sleep: vi.fn() }))

beforeEach(() => setActivePinia(createPinia()))

it('renders a playable immutable source with episode and media facts', () => {
  const wrapper = mount(RemakeSourceNode, {
    props: {
      id: 'remake-source-21',
      type: 'source_video',
      selected: false,
      data: {
        title: '来源视频 · 第 1 集',
        source: {
          id: 21,
          episode_number: 1,
          source_kind: 'upload',
          media_url: '/media/remake/source.mp4',
          original_filename: '第一集.mp4',
          size_bytes: 10485760,
          duration_seconds: 65,
          width: 1920,
          height: 1080,
          media_status: 'processing',
        },
      },
    } as never,
    global: { stubs: { WorkbenchNodeFrame: { template: '<article><slot /></article>' } } },
  })

  expect(wrapper.find('video').exists()).toBe(false)
  expect(wrapper.find('button[aria-label="播放第一集.mp4"]').exists()).toBe(true)
  expect(wrapper.text()).toContain('第一集.mp4')
  expect(wrapper.text()).toContain('01:05')
  expect(wrapper.text()).toContain('1920 × 1080')
  expect(wrapper.text()).toContain('上传视频')
})
