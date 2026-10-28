import { mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
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

it('keeps unavailable options explained and closes when the selector is locked', async () => {
  const wrapper = mount(WorkbenchSelect, { props: { modelValue: '1080p', label: '目标清晰度', options: [
    { value: '1080p', label: '1080P' }, { value: '2k', label: '2K', description: '服务未启用', disabled: true },
  ] } })
  await wrapper.get('[aria-label="目标清晰度"]').trigger('click')
  expect(wrapper.findAll('[role="option"]')[1]!.text()).toContain('服务未启用')
  await wrapper.setProps({ disabled: true })
  expect(wrapper.find('[role="listbox"]').exists()).toBe(false)
  await wrapper.get('[aria-label="目标清晰度"]').trigger('keydown', { key: 'ArrowDown' })
  expect(wrapper.find('[role="listbox"]').exists()).toBe(false)
  wrapper.unmount()
})


it('keeps option-navigation keys from moving selected canvas nodes', async () => {
  const wrapper = mount(WorkbenchSelect, { attachTo: document.body, props: { modelValue: '1080p', label: '目标清晰度',
    options: [{ value: '1080p', label: '1080P' }, { value: '2k', label: '2K' }] } })
  const canvasKey = vi.fn()
  document.body.addEventListener('keydown', canvasKey)
  try {
    await wrapper.get('[aria-label="目标清晰度"]').trigger('keydown', { key: 'ArrowDown' })
    await wrapper.get('[role="listbox"]').trigger('keydown', { key: 'ArrowDown' })
    expect(canvasKey).not.toHaveBeenCalled()
  } finally { document.body.removeEventListener('keydown', canvasKey); wrapper.unmount() }
})

it('opens below a canvas node when the viewport has space beyond the node boundary', async () => {
  const node = document.createElement('article')
  node.className = 'workbench-node-frame'
  document.body.append(node)
  const wrapper = mount(WorkbenchSelect, { attachTo: node, props: { modelValue: '1080p', label: '目标清晰度',
    options: ['720p','1080p','2k','4k'].map(value => ({ value, label: value })) } })
  node.getBoundingClientRect = () => ({ top: 200, bottom: 440 } as DOMRect)
  wrapper.get<HTMLElement>('[aria-label="目标清晰度"]').element.getBoundingClientRect = () => ({ top: 340, bottom: 380, height: 40 } as DOMRect)
  try {
    await wrapper.get('[aria-label="目标清晰度"]').trigger('click')
    expect(wrapper.get('[role="listbox"]').classes()).not.toContain('is-above')
  } finally { wrapper.unmount(); node.remove() }
})

it.each([
  { scale: .5, top: 400, viewport: 500, above: false },
  { scale: 2, top: 700, viewport: 1000, above: true },
  { scale: 1, top: 690, viewport: 768, above: true },
])('uses the zoomed menu height for scale $scale before opening above: $above', async ({ scale, top, viewport, above }) => {
  vi.stubGlobal('innerHeight', viewport)
  const wrapper = mount(WorkbenchSelect, { props: { modelValue: '1080p', label: '目标清晰度',
    options: ['720p','1080p','2k','4k'].map(value => ({ value, label: value })) } })
  const trigger = wrapper.get<HTMLElement>('[aria-label="目标清晰度"]').element
  Object.defineProperty(trigger, 'offsetHeight', { value: 40 })
  trigger.getBoundingClientRect = () => ({ top, bottom: top + 40 * scale, height: 40 * scale } as DOMRect)
  try {
    await wrapper.get('[aria-label="目标清晰度"]').trigger('click')
    expect(wrapper.get('[role="listbox"]').classes().includes('is-above')).toBe(above)
  } finally { wrapper.unmount(); vi.unstubAllGlobals() }
})
