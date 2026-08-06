import { afterEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import AppConfirmDialog from './AppConfirmDialog.vue'
import { appConfirm, resolveAppConfirm } from '@/shared/confirmDialog'

afterEach(() => {
  resolveAppConfirm(false)
  document.body.innerHTML = ''
})

describe('AppConfirmDialog', () => {
  it('renders shared destructive confirmation content', async () => {
    const wrapper = mount(AppConfirmDialog, { attachTo: document.body })
    const result = appConfirm({
      title: '删除分镜 16？',
      message: '删除后无法恢复。',
      confirmLabel: '删除分镜',
      tone: 'danger',
    })
    await nextTick()

    expect(document.querySelector('[role="alertdialog"]')).not.toBeNull()
    expect(document.body.textContent).toContain('删除分镜 16？')
    expect(document.body.textContent).toContain('删除后无法恢复。')
    expect(document.activeElement?.textContent).toContain('取消')

    await wrapper.findComponent({ name: 'AppButton' }).trigger('click')
    expect(await result).toBe(false)
  })

  it('resolves true from the confirm action', async () => {
    const wrapper = mount(AppConfirmDialog, { attachTo: document.body })
    const result = appConfirm({ title: '确认操作？', confirmLabel: '继续', tone: 'warning' })
    await nextTick()

    const buttons = wrapper.findAllComponents({ name: 'AppButton' })
    expect(buttons).toHaveLength(2)
    await buttons[1].trigger('click')
    expect(await result).toBe(true)
  })

  it('cancels with Escape and applies the dark surface', async () => {
    mount(AppConfirmDialog, { attachTo: document.body, props: { dark: true } })
    const result = appConfirm({ title: '删除项目？' })
    await nextTick()

    const backdrop = document.querySelector<HTMLElement>('.app-confirm-backdrop')!
    expect(backdrop.classList.contains('is-dark')).toBe(true)
    backdrop.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(await result).toBe(false)
  })
})
