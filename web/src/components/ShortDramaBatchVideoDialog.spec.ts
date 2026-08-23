import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import AppButton from './AppButton.vue'
import AppSelect from './AppSelect.vue'
import ShortDramaBatchVideoDialog from './ShortDramaBatchVideoDialog.vue'
import type { VideoGenerationModel } from '@/types'

const scenes = [
  { id: 11, sequence: 1, mode: 'reference' as const, duration: 6 },
  { id: 12, sequence: 2, mode: 'reference' as const, duration: 6, disabled: true, disabledReason: '已完成' },
  { id: 13, sequence: 3, mode: 'reference' as const, duration: 8 },
]

const models: VideoGenerationModel[] = [{
  config_id: 7,
  name: 'Seedance 2.5',
  model: 'seedance-endpoint',
  model_type: 'seedance_2_5',
  concurrency: 2,
  capabilities: {
    resolutions: ['720p', '1080p'], aspect_ratios: ['adaptive', '16:9'], aspect_ratios_by_mode: { reference: ['adaptive', '16:9'] },
    output_formats: ['mp4'], generation_modes: ['reference'], duration_min: 4, duration_max: 30,
    supports_auto_duration: true, supports_audio: true, supports_return_last_frame: true, max_reference_images: 30, max_reference_videos: 10,
    max_reference_audios: 10, reference_video_duration_max: 30, reference_video_total_duration_max: 30,
    reference_audio_duration_max: 30, reference_audio_total_duration_max: 30, reference_image_formats: ['png'], reference_video_formats: ['mp4'],
    reference_video_codecs: ['h264'], reference_video_audio_codecs: ['aac'], reference_video_resolutions: ['720p', '1080p'],
    reference_image_max_size_mb: 30, reference_video_max_size_mb: 200, reference_media_duration_min: 2, reference_media_ratio_min: 0.4,
    reference_media_ratio_max: 2.5, reference_media_side_min: 300, reference_media_side_max: 6000, reference_video_pixels_min: 409600,
    reference_video_pixels_max: 8295044, reference_video_fps_min: 24, reference_video_fps_max: 60,
    default_resolution: '720p', default_aspect_ratio: 'adaptive', default_output_format: 'mp4', default_generate_audio: true,
  },
}]

const global = { components: { AppButton }, stubs: { Teleport: true } }

afterEach(() => {
  document.body.innerHTML = ''
})

describe('ShortDramaBatchVideoDialog', () => {
  it('renders every scene while preventing unavailable scenes from being selected', () => {
    const wrapper = mount(ShortDramaBatchVideoDialog, {
      props: { open: true, scenes, models },
      global,
    })

    expect(wrapper.text()).toContain('批量生视频')
    expect(wrapper.findAll('.batch-video-scene')).toHaveLength(3)
    expect(wrapper.findAll('input[type="checkbox"]')[1]!.attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('.batch-video-scene')[1]!.attributes('title')).toBe('已完成')
  })

  it('supports selecting individual scenes and exposes a clear start action', async () => {
    const wrapper = mount(ShortDramaBatchVideoDialog, {
      props: { open: true, scenes, models },
      global,
    })

    const inputs = wrapper.findAll('input[type="checkbox"]')
    await inputs[0]!.setValue(true)
    await inputs[2]!.setValue(true)

    const submit = wrapper.find('.batch-video-dialog__submit')
    expect(submit.text()).toBe('开始')
    expect(submit.attributes('aria-label')).toBe('生成所选 2 条分镜视频')
    await submit.trigger('click')
    expect(wrapper.emitted('generate')).toEqual([[{
      sceneIds: [11, 13],
      modelConfigId: 7,
      resolution: '720p',
      aspectRatio: 'adaptive',
      returnLastFrame: false,
    }]])
  })

  it('applies one model, ratio and resolution and enables sequential last-frame generation', async () => {
    const wrapper = mount(ShortDramaBatchVideoDialog, {
      props: { open: true, scenes, models, initialResolution: '1080p', initialAspectRatio: '16:9' },
      global,
    })

    await wrapper.find('.batch-video-dialog__select-all').trigger('click')
    await wrapper.get('.batch-video-last-frame').trigger('click')
    expect(wrapper.get('.batch-video-last-frame').attributes('aria-checked')).toBe('true')
    expect(wrapper.get('.batch-video-last-frame').text()).toContain('按分镜顺序逐个执行')
    expect(wrapper.findAllComponents(AppSelect)).toHaveLength(3)
    await wrapper.get('.batch-video-dialog__submit').trigger('click')

    expect(wrapper.emitted('generate')).toEqual([[{
      sceneIds: [11, 13],
      modelConfigId: 7,
      resolution: '1080p',
      aspectRatio: '16:9',
      returnLastFrame: true,
    }]])
  })

  it('selects all eligible scenes and closes with Escape', async () => {
    const wrapper = mount(ShortDramaBatchVideoDialog, {
      props: { open: true, scenes, models },
      global,
    })

    await wrapper.find('.batch-video-dialog__select-all').trigger('click')
    expect(wrapper.find('.batch-video-dialog__submit').text()).toBe('开始')
    expect(wrapper.findAll('input[type="checkbox"]').map(input => (input.element as HTMLInputElement).checked)).toEqual([true, false, true])

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(wrapper.emitted('close')).toHaveLength(1)
  })
})
