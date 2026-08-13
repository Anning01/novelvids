import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import ImageGenerationParameterPanel from './ImageGenerationParameterPanel.vue'

const gptCapabilities = {
  clarities: ['low', 'medium', 'high'],
  aspect_ratios: ['1:1', '3:2', '2:3'],
  output_formats: ['png', 'jpeg', 'webp'],
  generation_counts: [1],
  default_clarity: 'medium',
  default_aspect_ratio: '1:1',
  default_output_format: 'png',
  default_generation_count: 1,
}

it('renders only backend-provided model capabilities and emits a selected value', async () => {
  const wrapper = mount(ImageGenerationParameterPanel, {
    props: {
      modelValue: { clarity: 'medium', aspectRatio: '1:1', outputFormat: 'png', generationCount: 1 },
      capabilities: gptCapabilities,
    },
    global: { stubs: { Teleport: true } },
  })

  await wrapper.get('.image-parameters__trigger').trigger('click')
  expect(wrapper.findAll('.image-parameters__ratios button').map(item => item.text())).toEqual(['1:1', '3:2', '2:3'])
  expect(wrapper.text()).not.toContain('16:9')

  const high = wrapper.findAll('.image-parameters__segments button').find(item => item.text() === '高')
  await high!.trigger('click')
  expect(wrapper.emitted('update:modelValue')?.at(-1)?.[0]).toEqual({
    clarity: 'high',
    aspectRatio: '1:1',
    outputFormat: 'png',
    generationCount: 1,
  })
})

it('keeps the summary ratio icon synchronized and fixes generation count to one', async () => {
  const wrapper = mount(ImageGenerationParameterPanel, {
    props: {
      modelValue: { clarity: 'medium', aspectRatio: '3:2', outputFormat: 'png', generationCount: 4 },
      capabilities: gptCapabilities,
    },
    global: { stubs: { Teleport: true } },
  })

  const ratioIcon = wrapper.get<HTMLElement>('[data-ratio-icon]')
  expect(Number.parseFloat(ratioIcon.element.style.width)).toBeGreaterThan(Number.parseFloat(ratioIcon.element.style.height))
  expect(wrapper.text()).toContain('1张')

  await wrapper.setProps({
    modelValue: { clarity: 'medium', aspectRatio: '2:3', outputFormat: 'png', generationCount: 4 },
  })
  expect(Number.parseFloat(ratioIcon.element.style.height)).toBeGreaterThan(Number.parseFloat(ratioIcon.element.style.width))

  await wrapper.get('.image-parameters__trigger').trigger('click')
  expect(wrapper.text()).not.toContain('生成数量')
  await wrapper.findAll('.image-parameters__segments button').find(item => item.text() === '高')!.trigger('click')
  expect(wrapper.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({ generationCount: 1 })
})
