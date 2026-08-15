import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import WorkbenchSelect from './WorkbenchSelect.vue'

it('opens an in-canvas listbox and emits the selected value', async () => {
  const wrapper = mount(WorkbenchSelect, {
    props: {
      modelValue: '1K',
      label: '尺寸',
      placeholder: '请选择尺寸',
      options: [
        { value: '1K', label: '1K（默认）' },
        { value: '2K', label: '2K', disabled: true },
      ],
    },
  })

  const trigger = wrapper.get('[aria-label="尺寸"]')
  expect(trigger.text()).toContain('1K（默认）')
  expect(trigger.attributes('aria-expanded')).toBe('false')

  await trigger.trigger('click')
  expect(trigger.attributes('aria-expanded')).toBe('true')
  expect(wrapper.get('[role="listbox"]').attributes('aria-label')).toBe('尺寸选项')

  const options = wrapper.findAll('[role="option"]')
  expect(options.map(option => option.text())).toEqual(['1K（默认）', '2K'])
  expect(options[0].attributes('aria-selected')).toBe('true')
  expect(options[1].attributes('disabled')).toBeDefined()

  await options[0].trigger('click')
  expect(wrapper.emitted('update:modelValue')).toEqual([['1K']])
  expect(wrapper.find('[role="listbox"]').exists()).toBe(false)
})

it('supports keyboard opening and Escape', async () => {
  const wrapper = mount(WorkbenchSelect, {
    props: {
      modelValue: '9:16',
      label: '画面比例',
      options: [
        { value: '16:9', label: '16:9' },
        { value: '9:16', label: '9:16' },
      ],
    },
  })

  const trigger = wrapper.get('[aria-label="画面比例"]')
  await trigger.trigger('keydown', { key: 'ArrowDown' })
  expect(wrapper.find('[role="listbox"]').exists()).toBe(true)

  await wrapper.get('[role="listbox"]').trigger('keydown', { key: 'Escape' })
  expect(wrapper.find('[role="listbox"]').exists()).toBe(false)
})

it('opens above when the prompt panel has no room below the trigger', async () => {
  const promptPanel = document.createElement('section')
  promptPanel.className = 'workbench-prompt-panel'
  document.body.append(promptPanel)
  const wrapper = mount(WorkbenchSelect, {
    attachTo: promptPanel,
    props: {
      modelValue: 'seedance',
      label: '视频模型',
      options: [
        { value: 'seedance', label: 'Seedance' },
        { value: 'fast', label: 'Seedance Fast' },
      ],
    },
  })
  const trigger = wrapper.get<HTMLElement>('[aria-label="视频模型"]')
  promptPanel.getBoundingClientRect = () => ({ top: 40, bottom: 240 } as DOMRect)
  trigger.element.getBoundingClientRect = () => ({ top: 200, bottom: 230 } as DOMRect)

  await trigger.trigger('click')

  expect(wrapper.get('.workbench-select').classes()).toContain('is-above')
  expect(wrapper.get('[role="listbox"]').classes()).toContain('is-above')
  wrapper.unmount()
  promptPanel.remove()
})
