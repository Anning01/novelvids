import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import AppSelect from './AppSelect.vue'
import AppButton from './AppButton.vue'

const options = ['wan3', 'minimax-h3', 'seedance-2.5', 'seedance-mini', 'seedance-fast', 'seedance']
const rect = (top: number, height: number): DOMRect => ({ top, bottom: top + height, left: 100, right: 320, width: 220, height, x: 100, y: top, toJSON: () => ({}) })
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

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
