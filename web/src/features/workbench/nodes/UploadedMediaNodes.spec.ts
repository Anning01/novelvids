import { createPinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import AudioMediaNode from './AudioMediaNode.vue'
import ImageMediaNode from './ImageMediaNode.vue'
import VideoMediaNode from './VideoMediaNode.vue'

const nodeFrameStub = { template: '<section><slot /></section>' }
const common = {
  id: 'media-1',
  type: 'image_media',
  selected: false,
  dragging: false,
  connectable: true,
  positionAbsoluteX: 0,
  positionAbsoluteY: 0,
  zIndex: 1,
  isValidTargetPos: false,
  isValidSourcePos: false,
}

function mountNode(component: typeof ImageMediaNode, data: Record<string, unknown>) {
  return mount(component, {
    props: { ...common, data } as never,
    global: {
      plugins: [createPinia()],
      stubs: {
        WorkbenchNodeFrame: nodeFrameStub,
        WorkbenchAudioMedia: { template: '<div data-audio-media />' },
      },
    },
  })
}

it('renders an uploaded image preview and exact replacement accept list', () => {
  const wrapper = mountNode(ImageMediaNode, {
    title: 'photo',
    url: '/media/photo.png',
    originalFilename: 'photo.png',
    width: 320,
    height: 180,
  })

  expect(wrapper.get('img').attributes()).toMatchObject({ src: '/media/photo.png', alt: 'photo预览' })
  expect(wrapper.text()).toContain('320 × 180')
  expect(wrapper.get('input[type="file"]').attributes()).toMatchObject({
    accept: 'image/png,image/jpeg,image/webp',
    'aria-label': '上传资产图片',
  })
})

it('renders uploaded video and audio replacement controls', () => {
  const video = mountNode(VideoMediaNode as typeof ImageMediaNode, {
    title: 'clip',
    url: '/media/clip.mp4',
    durationSeconds: 1,
  })
  const audio = mountNode(AudioMediaNode as typeof ImageMediaNode, {
    title: 'voice',
    url: '/media/voice.mp3',
    durationSeconds: 1,
  })

  expect(video.get('video').attributes('src')).toBe('/media/clip.mp4')
  expect(video.get('input[type="file"]').attributes('accept')).toBe('video/mp4,video/webm,video/quicktime')
  expect(audio.find('[data-audio-media]').exists()).toBe(true)
  expect(audio.get('input[type="file"]').attributes('accept')).toBe('audio/mpeg,audio/wav,audio/mp4,audio/webm')
})
