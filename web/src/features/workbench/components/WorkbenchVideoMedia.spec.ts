import { mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import WorkbenchVideoMedia from './WorkbenchVideoMedia.vue'

it('loads only the video after activation without a separate duration footer', async () => {
  const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
  const wrapper = mount(WorkbenchVideoMedia, {
    props: {
      src: '/media/video.mp4',
      title: '视频 01',
      ratio: '16:9',
    },
  })

  expect(wrapper.find('video').exists()).toBe(false)
  await wrapper.get('button[aria-label="播放视频 01"]').trigger('click')
  expect(wrapper.find('video').exists()).toBe(true)
  expect(wrapper.find('small').exists()).toBe(false)
  expect(wrapper.text()).not.toContain('秒')
  play.mockRestore()
})

it('reports intrinsic video dimensions after metadata loads', async () => {
  const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
  const wrapper = mount(WorkbenchVideoMedia, {
    props: {
      src: '/media/video.mp4',
      title: '视频 01',
      ratio: '16:9',
    },
  })
  await wrapper.get('button[aria-label="播放视频 01"]').trigger('click')
  const video = wrapper.get('video').element
  Object.defineProperties(video, {
    videoWidth: { configurable: true, value: 864 },
    videoHeight: { configurable: true, value: 496 },
  })

  await wrapper.get('video').trigger('loadedmetadata')

  expect(wrapper.emitted('metadata')).toEqual([[{ width: 864, height: 496 }]])
  expect(wrapper.get('.deferred-video-player').attributes('style')).toContain('aspect-ratio: 864 / 496')
  play.mockRestore()
})
