import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppButton from './AppButton.vue'
import SceneReferenceMediaBar from './SceneReferenceMediaBar.vue'
import type { VideoGenerationModel } from '@/types'

const model: VideoGenerationModel = {
  config_id: 7,
  name: 'Seedance 2.5',
  model: 'seedance-endpoint',
  model_type: 'seedance_2_5',
  concurrency: 2,
  capabilities: {
    resolutions: ['720p'], aspect_ratios: ['adaptive'], aspect_ratios_by_mode: { reference: ['adaptive'] },
    output_formats: ['mp4', 'mov'], generation_modes: ['reference', 'keyframes'], duration_min: 4, duration_max: 30,
    supports_auto_duration: true, supports_audio: true, supports_return_last_frame: true, max_reference_images: 30, max_reference_videos: 10,
    max_reference_audios: 10, reference_video_duration_max: 30, reference_video_total_duration_max: 30,
    reference_audio_duration_max: 30, reference_audio_total_duration_max: 30,
    reference_image_formats: ['jpg', 'png', 'webp'], reference_video_formats: ['mp4', 'mov'],
    reference_video_codecs: ['h264', 'hevc'], reference_video_audio_codecs: ['aac', 'mp3'],
    reference_video_resolutions: ['480p', '720p', '1080p', '4k'], reference_image_max_size_mb: 30,
    reference_video_max_size_mb: 200, reference_media_duration_min: 2, reference_media_ratio_min: 0.4,
    reference_media_ratio_max: 2.5, reference_media_side_min: 300, reference_media_side_max: 6000,
    reference_video_pixels_min: 409600, reference_video_pixels_max: 8295044, reference_video_fps_min: 24,
    reference_video_fps_max: 60, default_resolution: '720p', default_aspect_ratio: 'adaptive',
    default_output_format: 'mp4', default_generate_audio: true,
  },
}

describe('SceneReferenceMediaBar', () => {
  it('counts project asset images together with uploaded references', () => {
    const wrapper = mount(SceneReferenceMediaBar, {
      props: {
        model,
        assetImageCount: 3,
        media: [
          { type: 'image', url: '/media/look.png', name: 'look.png', width: 1024, height: 1024 },
          { type: 'video', url: '/media/move.mp4', name: 'move.mp4', duration: 8 },
        ],
      },
    })

    expect(wrapper.text()).toContain('图片 4/30')
    expect(wrapper.text()).toContain('视频 1/10')
    expect(wrapper.text()).toContain('8.0/30s')
    expect(wrapper.text()).toContain('资产图已计入')
    expect(wrapper.get('input').attributes('accept')).toContain('.mov')
    expect(wrapper.get('video.reference-video').attributes('src')).toBe('/media/move.mp4')
    expect((wrapper.get('video.reference-video').element as HTMLVideoElement).muted).toBe(true)
    expect(wrapper.get('.reference-name').text()).toContain('look.png')
    expect(wrapper.get('[aria-label="移除 look.png"] svg').classes()).toContain('lucide-x')
  })

  it('emits selected files and removal actions', async () => {
    const wrapper = mount(SceneReferenceMediaBar, {
      props: { model, assetImageCount: 0, media: [{ type: 'image', url: '/media/look.png', name: 'look.png' }] },
    })
    const file = new File(['image'], 'reference.png', { type: 'image/png' })
    const input = wrapper.get('input')
    Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })
    await input.trigger('change')
    await wrapper.get('[aria-label="移除 look.png"]').trigger('click')

    expect(wrapper.emitted('upload')).toEqual([[[file]]])
    expect(wrapper.emitted('remove')).toEqual([[0]])
  })

  it('opens the image lightbox when a reference thumbnail is clicked', async () => {
    const wrapper = mount(SceneReferenceMediaBar, {
      props: {
        model,
        assetImageCount: 0,
        media: [{ type: 'image', url: '/media/look.png', name: '首帧参考.png' }],
      },
      global: { components: { AppButton }, stubs: { Teleport: true } },
    })

    await wrapper.get('[aria-label="放大查看 首帧参考.png"]').trigger('click')

    const lightbox = wrapper.get('.image-lightbox')
    expect(lightbox.attributes('aria-label')).toBe('图片放大查看')
    expect(lightbox.get('img').attributes('src')).toBe('/media/look.png')
    expect(lightbox.get('img').attributes('alt')).toBe('首帧参考.png')
  })

  it('disables upload in keyframe mode', () => {
    const wrapper = mount(SceneReferenceMediaBar, {
      props: { model, assetImageCount: 0, media: [], disabled: true },
    })
    expect(wrapper.get('[aria-label="上传参考图片或视频"]').attributes()).toHaveProperty('disabled')
  })

  it('marks the provider-rejected upload for quick location', () => {
    const wrapper = mount(SceneReferenceMediaBar, {
      props: {
        model,
        assetImageCount: 0,
        highlightedMediaIndex: 1,
        media: [
          { type: 'image', url: '/media/one.png', name: '第一张' },
          { type: 'image', url: '/media/two.png', name: '第二张' },
        ],
      },
    })

    expect(wrapper.get('[data-reference-media-index="1"]').classes()).toContain('is-reference-highlighted')
    expect(wrapper.get('[data-reference-media-index="0"]').classes()).not.toContain('is-reference-highlighted')
  })
})
