import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { expect, it } from 'vitest'
import ImageGenerationParameterPanel from './ImageGenerationParameterPanel.vue'
import MediaGenerationModelSelector from '@/features/workbench/components/MediaGenerationModelSelector.vue'

const gptCapabilities = {
  clarities: ['1K', '2K', '4K'],
  aspect_ratios: ['1:1', '3:2', '2:3'],
  output_formats: ['png', 'jpeg', 'webp'],
  generation_counts: [1],
  default_clarity: '1K',
  default_aspect_ratio: '1:1',
  default_output_format: 'png',
  default_generation_count: 1,
}

it('applies format-specific resolution capabilities when choosing GIF', async () => {
  const wrapper = mount(ImageGenerationParameterPanel, {props:{
    modelValue:{clarity:'4K',aspectRatio:'1:1',outputFormat:'png',generationCount:1},
    capabilities:{...gptCapabilities,output_formats:['png','gif'],clarities_by_format:{gif:['1K']}},
  },global:{stubs:{Teleport:true}}})
  await wrapper.get('.image-parameters__trigger').trigger('click')
  await wrapper.findAll('.image-parameters__segments button').find(button => button.text()==='GIF')!.trigger('click')
  expect(wrapper.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({outputFormat:'gif',clarity:'1K'})
  await wrapper.setProps({modelValue:{clarity:'1K',aspectRatio:'1:1',outputFormat:'gif',generationCount:1}})
  const quality = wrapper.findAll('.image-parameters__segments').at(0)!
  expect(quality.findAll('button').map(button => button.text())).toEqual(['1K'])
  wrapper.unmount()
})

it.each(['light', 'dark'])('新 GPT Image 只展示后台提供的 1K/2K/4K，参数可切换为 2K（%s）', async theme => {
  document.documentElement.dataset.appTheme = theme
  const wrapper = mount(ImageGenerationParameterPanel, {
    props: { modelValue: { clarity: '4K', aspectRatio: '1:1', outputFormat: 'png', generationCount: 1 },
      capabilities: { ...gptCapabilities, clarities: ['1K', '2K', '4K'], default_clarity: '1K' } },
    global: { stubs: { Teleport: true } },
  })
  await wrapper.get('.image-parameters__trigger').trigger('click')
  const choices = wrapper.findAll('.image-parameters__segments').at(0)!.findAll('button')
  expect(choices.map(choice => choice.text())).toEqual(['1K', '2K', '4K'])
  await choices[1]!.trigger('click')
  expect(wrapper.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({ clarity: '2K' })
  wrapper.unmount()
  delete document.documentElement.dataset.appTheme
})

it('renders only backend-provided model capabilities and emits a selected value', async () => {
  const wrapper = mount(ImageGenerationParameterPanel, {
    props: {
      modelValue: { clarity: '1K', aspectRatio: '1:1', outputFormat: 'png', generationCount: 1 },
      capabilities: gptCapabilities,
    },
    global: { stubs: { Teleport: true } },
  })

  await wrapper.get('.image-parameters__trigger').trigger('click')
  expect(wrapper.findAll('.image-parameters__ratios button').map(item => item.text())).toEqual(['1:1', '3:2', '2:3'])
  expect(wrapper.text()).not.toContain('16:9')
  const lightPanelStyle = wrapper.get('[role="dialog"][aria-label="图片生成参数"]').attributes('style')
  expect(lightPanelStyle).toContain('--app-surface-raised: #fff')
  expect(lightPanelStyle).toContain('color-scheme: light')

  const high = wrapper.findAll('.image-parameters__segments button').find(item => item.text() === '4K')
  await high!.trigger('click')
  expect(wrapper.emitted('update:modelValue')?.at(-1)?.[0]).toEqual({
    clarity: '4K',
    aspectRatio: '1:1',
    outputFormat: 'png',
    generationCount: 1,
  })
})

it('keeps the summary ratio icon synchronized and fixes generation count to one', async () => {
  const wrapper = mount(ImageGenerationParameterPanel, {
    props: {
      modelValue: { clarity: '1K', aspectRatio: '3:2', outputFormat: 'png', generationCount: 4 },
      capabilities: gptCapabilities,
    },
    global: { stubs: { Teleport: true } },
  })

  const ratioIcon = wrapper.get<HTMLElement>('[data-ratio-icon]')
  expect(Number.parseFloat(ratioIcon.element.style.width)).toBeGreaterThan(Number.parseFloat(ratioIcon.element.style.height))
  expect(wrapper.text()).toContain('1张')

  await wrapper.setProps({
    modelValue: { clarity: '1K', aspectRatio: '2:3', outputFormat: 'png', generationCount: 4 },
  })
  expect(Number.parseFloat(ratioIcon.element.style.height)).toBeGreaterThan(Number.parseFloat(ratioIcon.element.style.width))

  await wrapper.get('.image-parameters__trigger').trigger('click')
  expect(wrapper.text()).not.toContain('生成数量')
  await wrapper.findAll('.image-parameters__segments button').find(item => item.text() === '4K')!.trigger('click')
  expect(wrapper.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({ generationCount: 1 })
})

it('keeps the model list and image parameter panel mutually exclusive', async () => {
  const harness = defineComponent({
    components: { ImageGenerationParameterPanel, MediaGenerationModelSelector },
    setup: () => ({
      capabilities: gptCapabilities,
      parameters: { clarity: '1K', aspectRatio: '1:1', outputFormat: 'png', generationCount: 1 },
      modelOptions: [{ value: 9, label: 'Seedream 5.0' }],
    }),
    template: `
      <div>
        <MediaGenerationModelSelector :model-value="9" :options="modelOptions" />
        <ImageGenerationParameterPanel :model-value="parameters" :capabilities="capabilities" />
      </div>
    `,
  })
  const wrapper = mount(harness, { global: { stubs: { Teleport: true } } })

  await wrapper.get('[aria-label="视频模型"]').trigger('click')
  expect(wrapper.find('[role="listbox"]').exists()).toBe(true)

  await wrapper.get('[aria-label="设置图片生成参数"]').trigger('click')
  expect(wrapper.find('[role="listbox"]').exists()).toBe(false)
  expect(wrapper.find('[role="dialog"][aria-label="图片生成参数"]').exists()).toBe(true)

  await wrapper.get('[aria-label="视频模型"]').trigger('click')
  expect(wrapper.find('[role="dialog"][aria-label="图片生成参数"]').exists()).toBe(false)
  expect(wrapper.find('[role="listbox"]').exists()).toBe(true)
  wrapper.unmount()
})

it('carries the workflow theme into the teleported image parameter panel', async () => {
  const surface = document.createElement('div')
  surface.style.setProperty('--vf-bg-elevated', '#211e1b')
  surface.style.setProperty('--vf-text-primary', '#eee9e2')
  surface.style.setProperty('--vf-border-strong', '#645a51')
  surface.style.colorScheme = 'dark'
  document.body.append(surface)
  const wrapper = mount(ImageGenerationParameterPanel, {
    attachTo: surface,
    props: {
      modelValue: { clarity: '1K', aspectRatio: '1:1', outputFormat: 'png', generationCount: 1 },
      capabilities: gptCapabilities,
    },
    global: { stubs: { Teleport: true } },
  })

  await wrapper.get('[aria-label="设置图片生成参数"]').trigger('click')
  const panelStyle = wrapper.get('[role="dialog"][aria-label="图片生成参数"]').attributes('style')
  expect(panelStyle).toContain('--app-surface-raised: #211e1b')
  expect(panelStyle).toContain('--app-text: #eee9e2')
  expect(panelStyle).toContain('--app-border-strong: #645a51')
  expect(panelStyle).toContain('color-scheme: dark')
  wrapper.unmount()
  surface.remove()
})
