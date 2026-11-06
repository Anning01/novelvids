import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import AppSelect from './AppSelect.vue'
import AppButton from './AppButton.vue'

const options = ['wan3', 'minimax-h3', 'seedance-2.5', 'seedance-mini', 'seedance-fast', 'seedance']
const rect = (top: number, height: number): DOMRect => ({ top, bottom: top + height, left: 100, right: 320, width: 220, height, x: 100, y: top, toJSON: () => ({}) })
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('keeps the trigger surface theme when its menu is teleported', async () => {
  const wrapper = mount(AppSelect, { props: { modelValue: 'one', options: ['one', 'two'], ariaLabel: '主题菜单' },
    attrs: { style: '--app-surface: #211e1b; --app-text: #eee9e2; --app-accent: #b8a7ff' },
    global: { components: { AppButton } } })
  await wrapper.get('button').trigger('click'); await flushPromises()
  const menu = document.querySelector<HTMLElement>('[role="listbox"][aria-label="主题菜单"]')!
  expect(menu.style.getPropertyValue('--app-surface')).toBe('#211e1b')
  expect(menu.style.getPropertyValue('--app-text')).toBe('#eee9e2')
  expect(menu.style.getPropertyValue('--app-accent')).toBe('#b8a7ff')
  wrapper.unmount()
})

it.each([['compact', 206], ['default', 254]] as const)('anchors an upward %s menu using its rendered height', async (density, height) => {
  vi.stubGlobal('innerHeight', 650)
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    return this.classList.contains('app-select__menu') ? rect(0, height) : rect(560, 34)
  })
  const wrapper = mount(AppSelect, { props: { modelValue: 'wan3', options, ariaLabel: '视频模型', density }, global: { components: { AppButton } } })
  await wrapper.get('button').trigger('click'); await flushPromises()
  const menu = document.body.querySelector<HTMLElement>('[role="listbox"]')!
  expect(menu.classList.contains('is-up')).toBe(true)
  expect(560 - (Number.parseFloat(menu.style.top) + height)).toBe(7)
})

it('consumes Escape while the menu is open and releases it once closed', async () => {
  const bubbled = vi.fn()
  window.addEventListener('keydown', bubbled)
  const wrapper = mount(AppSelect, { attachTo: document.body, props: { modelValue: 'one', options: ['one', 'two'], ariaLabel: '主题菜单' },
    global: { components: { AppButton } } })
  await wrapper.get('button').trigger('click'); await flushPromises()
  expect(document.querySelector('.app-select__menu')).not.toBeNull()
  await wrapper.get('button').trigger('keydown', { key: 'Escape' }); await flushPromises()
  expect(document.querySelector('.app-select__menu')).toBeNull()
  expect(bubbled).not.toHaveBeenCalled()
  await wrapper.get('button').trigger('keydown', { key: 'Escape' }); await flushPromises()
  expect(bubbled).toHaveBeenCalled()
  window.removeEventListener('keydown', bubbled)
  wrapper.unmount()
})

it('uses available space and updates the anchor when its container scrolls', async () => {
  vi.stubGlobal('innerHeight', 650)
  let triggerTop = 40
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    return this.classList.contains('app-select__menu') ? rect(0, 206) : rect(triggerTop, 34)
  })
  const wrapper = mount(AppSelect, { props: { modelValue: 'wan3', options, ariaLabel: '视频模型' }, global: { components: { AppButton } } })
  await wrapper.get('button').trigger('click'); await flushPromises()
  const menu = document.body.querySelector<HTMLElement>('[role="listbox"]')!
  expect(menu.classList.contains('is-up')).toBe(false)
  expect(Number.parseFloat(menu.style.top)).toBe(81)
  triggerTop = 560
  window.dispatchEvent(new Event('scroll')); await flushPromises()
  expect(menu.classList.contains('is-up')).toBe(true)
  expect(560 - (Number.parseFloat(menu.style.top) + 206)).toBe(7)
})

it.each(['light', 'dark'])('supports keyboard selection and restores focus in %s mode', async theme => {
  const host = document.createElement('div')
  host.dataset.appTheme = theme
  document.body.append(host)
  const wrapper = mount(AppSelect, {
    attachTo: host,
    props: { modelValue: 'one', options: ['one', 'two'], ariaLabel: '键盘下拉' },
  })
  try {
    const trigger = wrapper.get('button')
    trigger.element.focus()
    await trigger.trigger('keydown', { key: 'ArrowDown' })
    const menu = document.querySelector('[role="listbox"][aria-label="键盘下拉"]')!
    const [first, second] = [...menu.querySelectorAll<HTMLButtonElement>('[role="option"]')]
    expect(document.activeElement).toBe(first)
    first!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
    expect(document.activeElement).toBe(second)
    second!.click()
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')).toEqual([['two']])
    expect(document.activeElement).toBe(trigger.element)
    expect(trigger.attributes('aria-expanded')).toBe('false')
    await wrapper.setProps({ disabled: true })
    expect(trigger.element.disabled).toBe(true)
  } finally {
    wrapper.unmount()
    host.remove()
  }
})

it('fits menu width to content and reserves checkmark slot for all options', async () => {
  const wrapper = mount(AppSelect, {
    attachTo: document.body,
    props: { modelValue: 'wan3', options: ['wan3', 'doubao-seedance-2-0-mini'], ariaLabel: '模型选择' },
    global: { components: { AppButton } },
  })
  try {
    await wrapper.get('button').trigger('click')
    await flushPromises()
    const menu = document.body.querySelector<HTMLElement>('[role="listbox"][aria-label="模型选择"]')!
    expect(menu.style.width).toBe('max-content')
    const options = menu.querySelectorAll('[role="option"]')
    expect(options).toHaveLength(2)

    const firstCheck = options[0]?.querySelector('.app-select__check')
    const secondCheck = options[1]?.querySelector('.app-select__check')
    expect(firstCheck).not.toBeNull()
    expect(firstCheck?.classList.contains('is-invisible')).toBe(false)
    expect(secondCheck).not.toBeNull()
    expect(secondCheck?.classList.contains('is-invisible')).toBe(true)
  } finally {
    wrapper.unmount()
  }
})

it('respects explicit menuWidth when provided', async () => {
  const wrapper = mount(AppSelect, {
    attachTo: document.body,
    props: { modelValue: 'wan3', options: ['wan3'], ariaLabel: '固定宽度', menuWidth: 240 },
    global: { components: { AppButton } },
  })
  try {
    await wrapper.get('button').trigger('click')
    await flushPromises()
    const menu = document.body.querySelector<HTMLElement>('[role="listbox"][aria-label="固定宽度"]')!
    expect(menu.style.width).toBe('240px')
  } finally {
    wrapper.unmount()
  }
})
