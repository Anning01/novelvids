import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import WorkbenchVideoMedia from './WorkbenchVideoMedia.vue'

it('renders only the video without a separate duration footer', () => {
  const wrapper = mount(WorkbenchVideoMedia, {
    props: {
      src: '/media/video.mp4',
      title: '视频 01',
      ratio: '16:9',
    },
  })

  expect(wrapper.find('video').exists()).toBe(true)
  expect(wrapper.find('small').exists()).toBe(false)
  expect(wrapper.text()).not.toContain('秒')
})

it('reports intrinsic video dimensions after metadata loads', async () => {
  const wrapper = mount(WorkbenchVideoMedia, {
    props: {
      src: '/media/video.mp4',
      title: '视频 01',
      ratio: '16:9',
    },
  })
  const video = wrapper.get('video').element
  Object.defineProperties(video, {
    videoWidth: { configurable: true, value: 864 },
    videoHeight: { configurable: true, value: 496 },
  })

  await wrapper.get('video').trigger('loadedmetadata')

  expect(wrapper.emitted('metadata')).toEqual([[{ width: 864, height: 496 }]])
  expect(wrapper.get('video').attributes('style')).toContain('aspect-ratio: 864 / 496')
})
