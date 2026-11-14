import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import StoryboardGenerationOptions from './StoryboardGenerationOptions.vue'

it.each(['light', 'dark'])('keeps blocking maps optional and independent from sheets in %s', async theme => {
  document.documentElement.dataset.appTheme = theme
  const wrapper = mount(StoryboardGenerationOptions, { props: { modelValue: '', enabled: false, disabled: false },
    global: { stubs: { ImageModelSelect: true } } })
  const inputs = wrapper.findAll('input')
  expect((inputs[0]!.element as HTMLInputElement).checked).toBe(false)
  await inputs[0]!.setValue(true)
  expect(wrapper.emitted('update:blockingMaps')).toEqual([[true]])
  expect(wrapper.emitted('toggle')).toBeUndefined()
  await wrapper.setProps({ disabled: true })
  expect(inputs.every(input => input.attributes('disabled') !== undefined)).toBe(true)
  wrapper.unmount()
  delete document.documentElement.dataset.appTheme
})
