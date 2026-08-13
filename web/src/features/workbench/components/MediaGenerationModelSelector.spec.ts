import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import MediaGenerationModelSelector from './MediaGenerationModelSelector.vue'

it('renders backend model labels and emits the selected numeric model type', async () => {
  const wrapper = mount(MediaGenerationModelSelector, {
    props: {
      modelValue: 1,
      options: [
        { value: 1, label: 'Vidu Q2' },
        { value: 3, label: 'Seedance' },
      ],
    },
  })

  await wrapper.get('[aria-label="视频模型"]').trigger('click')
  await wrapper.get('[role="option"][aria-selected="false"]').trigger('click')

  expect(wrapper.emitted('update:modelValue')).toEqual([[3]])
})
