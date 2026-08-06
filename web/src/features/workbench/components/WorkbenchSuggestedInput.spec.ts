import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import WorkbenchSuggestedInput from './WorkbenchSuggestedInput.vue'

const suggestions = [
  { value: '1024x1024', label: '1K · 1:1 · 1024×1024' },
  { value: '1424x800', label: '1K · 16:9 · 1424×800（默认）' },
]

it('renders an editable input with an in-place dark suggestion list', async () => {
  const wrapper = mount(WorkbenchSuggestedInput, {
    props: {
      modelValue: '1424x800',
      label: '尺寸',
      suggestions,
    },
  })

  const toggle = wrapper.get('[aria-label="打开尺寸推荐值"]')
  expect(toggle.attributes('aria-expanded')).toBe('false')

  await toggle.trigger('click')
  expect(wrapper.get('[role="listbox"]').attributes('aria-label')).toBe('尺寸推荐值')
  expect(wrapper.findAll('[role="option"]').map(option => option.text())).toEqual([
    '1024x10241K · 1:1 · 1024×1024',
    '1424x8001K · 16:9 · 1424×800（默认）',
  ])
  expect(wrapper.findAll('[role="option"]')[1].attributes('aria-selected')).toBe('true')
  expect(wrapper.get('[aria-label="关闭尺寸推荐值"]').attributes('aria-expanded')).toBe('true')
})

it('supports custom text and closes after selecting a suggestion', async () => {
  const wrapper = mount(WorkbenchSuggestedInput, {
    props: {
      modelValue: '1424x800',
      label: '尺寸',
      suggestions,
    },
  })

  await wrapper.get('input').setValue('1280x960')
  expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['1280x960'])

  await wrapper.get('[aria-label="打开尺寸推荐值"]').trigger('click')
  await wrapper.findAll('[role="option"]')[0].trigger('click')

  expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['1024x1024'])
  expect(wrapper.find('[role="listbox"]').exists()).toBe(false)
})
