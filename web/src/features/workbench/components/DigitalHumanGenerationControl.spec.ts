import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import DigitalHumanGenerationControl from './DigitalHumanGenerationControl.vue'

it('opens the digital-human picker and exposes removal only for a selection', async () => {
  const wrapper = mount(DigitalHumanGenerationControl, {
    props: {
      title: 'human-one',
      previewUrl: '/media/human-one.png',
      selected: true,
    },
  })

  await wrapper.get('[aria-label="更换数字人 human-one"]').trigger('click')
  await wrapper.get('[aria-label="移除数字人人物"]').trigger('click')

  expect(wrapper.emitted('open')).toHaveLength(1)
  expect(wrapper.emitted('clear')).toHaveLength(1)
  expect(wrapper.get('img').attributes('src')).toBe('/media/human-one.png')
})
