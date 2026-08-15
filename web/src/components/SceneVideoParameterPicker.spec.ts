import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { describe, expect, it } from 'vitest'
import SceneVideoParameterPicker from './SceneVideoParameterPicker.vue'
import type { VideoGenerationModel } from '@/types'
import MediaGenerationModelSelector from '@/features/workbench/components/MediaGenerationModelSelector.vue'

const model = {
  config_id: 9,
  name: 'Seedance 2.5',
  model: 'seedance-2.5-endpoint',
  model_type: 'seedance_2_5',
  concurrency: 2,
  capabilities: {
    resolutions: ['480p', '720p'], aspect_ratios: ['16:9', '9:16', '1:1', 'adaptive'],
    aspect_ratios_by_mode: { reference: ['16:9', '9:16', '1:1', 'adaptive'], keyframes: ['adaptive'] },
    output_formats: ['mp4', 'mov'], generation_modes: ['reference', 'keyframes'], duration_min: 4, duration_max: 30,
    supports_auto_duration: true, supports_audio: true, supports_return_last_frame: true,
    max_reference_images: 30, max_reference_videos: 10, max_reference_audios: 10,
    reference_video_duration_max: 30, reference_video_total_duration_max: 30,
    reference_audio_duration_max: 30, reference_audio_total_duration_max: 30,
    reference_image_formats: ['jpg', 'png'], reference_video_formats: ['mp4', 'mov'],
    reference_video_codecs: ['h264', 'hevc'], reference_video_audio_codecs: ['aac', 'mp3'],
    reference_video_resolutions: ['480p', '720p', '1080p', '4k'], reference_image_max_size_mb: 30,
    reference_video_max_size_mb: 200, reference_media_duration_min: 2, reference_media_ratio_min: 0.4,
    reference_media_ratio_max: 2.5, reference_media_side_min: 300, reference_media_side_max: 6000,
    reference_video_pixels_min: 409600, reference_video_pixels_max: 8295044,
    reference_video_fps_min: 24, reference_video_fps_max: 60,
    default_resolution: '720p', default_aspect_ratio: 'adaptive', default_output_format: 'mp4',
    default_generate_audio: true,
  },
} satisfies VideoGenerationModel

describe('SceneVideoParameterPicker', () => {
  it('renders model capabilities and emits parameter changes', async () => {
    const wrapper = mount(SceneVideoParameterPicker, {
      props: {
        model,
        mode: 'reference',
        duration: 6,
        aspectRatio: '16:9',
        resolution: '720p',
        returnLastFrame: false,
      },
      global: { stubs: { Teleport: true } },
    })

    expect(wrapper.text()).toContain('6秒 · 16:9 · 720p')
    await wrapper.get('[aria-label="设置视频时长、比例、分辨率和尾帧衔接"]').trigger('click')
    expect(wrapper.text()).toContain('当前 6 秒')
    expect(wrapper.text()).toContain('最短 4 秒')
    expect(wrapper.text()).toContain('最长 30 秒')
    expect(wrapper.text()).toContain('画面比例')
    expect(wrapper.text()).toContain('480p')
    expect(wrapper.text()).toContain('返回尾帧')
    const lightPanelStyle = wrapper.get('[role="dialog"][aria-label="视频生成参数"]').attributes('style')
    expect(lightPanelStyle).toContain('--app-surface-raised: #fff')
    expect(lightPanelStyle).toContain('color-scheme: light')

    await wrapper.get('input[type="range"]').setValue('12')
    const ratioButton = wrapper.findAll('button').find(button => button.text() === '9:16')
    const resolutionButton = wrapper.findAll('button').find(button => button.text() === '480p')
    await ratioButton?.trigger('click')
    await resolutionButton?.trigger('click')
    await wrapper.get('[role="switch"]').trigger('click')

    expect(wrapper.emitted('update:duration')).toEqual([[12]])
    expect(wrapper.emitted('update:aspectRatio')).toEqual([['9:16']])
    expect(wrapper.emitted('update:resolution')).toEqual([['480p']])
    expect(wrapper.emitted('update:returnLastFrame')).toEqual([[true]])
  })

  it('uses mode-specific ratios from the selected model', async () => {
    const wrapper = mount(SceneVideoParameterPicker, {
      props: {
        model,
        mode: 'keyframes',
        duration: 30,
        aspectRatio: '16:9',
        resolution: '720p',
        returnLastFrame: true,
      },
      global: { stubs: { Teleport: true } },
    })

    expect(wrapper.text()).toContain('30秒 · 自适应 · 720p')
    await wrapper.get('[aria-label="设置视频时长、比例、分辨率和尾帧衔接"]').trigger('click')
    expect(wrapper.findAll('.ratio-grid button')).toHaveLength(1)
    expect(wrapper.get('.ratio-grid button').text()).toBe('AUTO自适应')
  })

  it('updates the compact trigger icon when the aspect ratio changes', async () => {
    const wrapper = mount(SceneVideoParameterPicker, {
      props: {
        model,
        mode: 'reference',
        duration: 6,
        aspectRatio: '16:9',
        resolution: '720p',
        returnLastFrame: false,
      },
      global: { stubs: { Teleport: true } },
    })

    expect(wrapper.get('.summary-icon').attributes('style')).toContain('width: 21px')
    await wrapper.setProps({ aspectRatio: '9:16' })
    expect(wrapper.get('.summary-icon').attributes('style')).toContain('width: 12px')
    expect(wrapper.get('.summary-icon').attributes('style')).toContain('height: 18px')
    await wrapper.setProps({ aspectRatio: '1:1' })
    expect(wrapper.get('.summary-icon').attributes('style')).toContain('width: 12px')
    expect(wrapper.get('.summary-icon').attributes('style')).toContain('height: 12px')
  })

  it('keeps the model list and parameter panel mutually exclusive', async () => {
    const harness = defineComponent({
      components: { MediaGenerationModelSelector, SceneVideoParameterPicker },
      setup: () => ({
        model,
        modelOptions: [{ value: 9, label: 'Seedance 2.5' }],
      }),
      template: `
        <div>
          <MediaGenerationModelSelector :model-value="9" :options="modelOptions" />
          <SceneVideoParameterPicker
            :model="model"
            mode="reference"
            :duration="6"
            aspect-ratio="16:9"
            resolution="720p"
            :return-last-frame="false"
          />
        </div>
      `,
    })
    const wrapper = mount(harness, { global: { stubs: { Teleport: true } } })

    await wrapper.get('[aria-label="视频模型"]').trigger('click')
    expect(wrapper.find('[role="listbox"]').exists()).toBe(true)

    await wrapper.get('[aria-label="设置视频时长、比例、分辨率和尾帧衔接"]').trigger('click')
    expect(wrapper.find('[role="listbox"]').exists()).toBe(false)
    expect(wrapper.find('[role="dialog"][aria-label="视频生成参数"]').exists()).toBe(true)

    await wrapper.get('[aria-label="视频模型"]').trigger('click')
    expect(wrapper.find('[role="dialog"][aria-label="视频生成参数"]').exists()).toBe(false)
    expect(wrapper.find('[role="listbox"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('carries the workflow surface theme into the teleported parameter panel', async () => {
    const surface = document.createElement('div')
    surface.className = 'viral-workbench-surface-theme'
    surface.style.setProperty('--vf-bg-elevated', '#211e1b')
    surface.style.setProperty('--vf-text-primary', '#eee9e2')
    surface.style.setProperty('--vf-border-strong', '#645a51')
    surface.style.colorScheme = 'dark'
    document.body.append(surface)
    const wrapper = mount(SceneVideoParameterPicker, {
      attachTo: surface,
      props: {
        model,
        mode: 'reference',
        duration: 6,
        aspectRatio: '16:9',
        resolution: '720p',
        returnLastFrame: false,
      },
      global: { stubs: { Teleport: true } },
    })

    await wrapper.get('[aria-label="设置视频时长、比例、分辨率和尾帧衔接"]').trigger('click')
    const panelStyle = wrapper.get('[role="dialog"][aria-label="视频生成参数"]').attributes('style')
    expect(panelStyle).toContain('--app-surface-raised: #211e1b')
    expect(panelStyle).toContain('--app-text: #eee9e2')
    expect(panelStyle).toContain('--app-border-strong: #645a51')
    expect(panelStyle).toContain('color-scheme: dark')
    wrapper.unmount()
    surface.remove()
  })
})
