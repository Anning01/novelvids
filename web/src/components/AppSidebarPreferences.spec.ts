import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import { useAuthStore } from '@/features/auth/authStore'
import { applySavedLocale, locale, setLocale } from '@/i18n'
import AppSidebarPreferences from './AppSidebarPreferences.vue'
import { notice } from '@/shared/notice'

vi.mock('@/shared/notice', () => ({ notice: { error: vi.fn(), success: vi.fn() } }))

vi.mock('@/api', () => ({
  api: { generalConfig: vi.fn(), updateGeneralConfig: vi.fn() },
  getAuthToken: () => null, getActiveTeamId: () => null,
}))
const wrappers: ReturnType<typeof mount>[] = []
function render(admin = true, showTheme = true) {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().$patch({ enabled: admin ? false : true })
  const wrapper = mount(AppSidebarPreferences, { attachTo: document.body, props: { showTheme }, global: { plugins: [pinia] } })
  wrappers.push(wrapper)
  return wrapper
}
beforeEach(() => {
  vi.resetAllMocks()
  setLocale('zh')
  vi.mocked(api.generalConfig).mockResolvedValue({ code: 0, message: '', data: { id: 1, created_at: '', updated_at: '', prompt_language: 'zh' } })
  vi.mocked(api.updateGeneralConfig).mockResolvedValue({ code: 0, message: '', data: { id: 1, created_at: '', updated_at: '', prompt_language: 'en' } })
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); applySavedLocale('zh') })

it.each(['light', 'dark'])('switches immediately from a compact menu and saves automatically (%s)', async theme => {
  document.documentElement.dataset.appTheme = theme
  let finish!: (response: Awaited<ReturnType<typeof api.updateGeneralConfig>>) => void
  vi.mocked(api.updateGeneralConfig).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
  const wrapper = render()
  expect(wrapper.get('.sidebar-language__value').text()).toBe('中文')
  await wrapper.get('.sidebar-language__trigger').trigger('click')
  await flushPromises()
  expect(api.generalConfig).toHaveBeenCalledOnce()
  expect(wrapper.findAll('[role="menuitemradio"]').map(option => option.text())).toEqual(['简体中文', 'English'])
  expect(wrapper.find('.preference-menu__panel header').exists()).toBe(false)
  expect(wrapper.find('.sidebar-language__note').exists()).toBe(false)
  expect(wrapper.find('.app-button--primary').exists()).toBe(false)
  await wrapper.findAll('[role="menuitemradio"]')[1]!.trigger('click')
  expect(api.updateGeneralConfig).toHaveBeenCalledWith({ prompt_language: 'en' })
  expect(locale.value).toBe('en')
  expect(wrapper.get('.sidebar-language__trigger').attributes('aria-busy')).toBe('true')
  expect(wrapper.find('[role="menu"]').exists()).toBe(false)
  expect(document.activeElement).toBe(wrapper.get('.sidebar-language__trigger').element)
  finish({ code: 0, message: '', data: { id: 1, created_at: '', updated_at: '', prompt_language: 'en' } })
  await flushPromises()
  expect(wrapper.get('.sidebar-language__trigger').attributes('aria-busy')).toBe('false')
  delete document.documentElement.dataset.appTheme
})

it('shows read-only language and an administrator hint for ordinary members', async () => {
  const wrapper = render(false)
  await wrapper.get('.sidebar-language__trigger').trigger('click')
  await flushPromises()
  expect(api.generalConfig).not.toHaveBeenCalled()
  expect(wrapper.findAll('[role="menuitemradio"]').every(radio => radio.attributes('disabled') !== undefined)).toBe(true)
  expect(wrapper.text()).toContain('由管理员设置')
  expect(wrapper.find('.app-button--primary').exists()).toBe(false)
})

it('saves keyboard selection immediately and dismisses without writing when no selection changes', async () => {
  const wrapper = render()
  await wrapper.get('.sidebar-language__trigger').trigger('click')
  await flushPromises()
  await wrapper.get('[role="menu"]').trigger('keydown', { key: 'ArrowDown' })
  await wrapper.get('[role="menu"]').trigger('keydown', { key: 'Enter' })
  await flushPromises()
  expect(locale.value).toBe('en')
  expect(api.updateGeneralConfig).toHaveBeenCalledOnce()
  expect(wrapper.find('[role="menu"]').exists()).toBe(false)
  vi.mocked(api.generalConfig).mockResolvedValueOnce({ code: 0, message: '', data: { id: 1, created_at: '', updated_at: '', prompt_language: 'en' } })
  await wrapper.get('.sidebar-language__trigger').trigger('click')
  await flushPromises()
  expect(wrapper.findAll('[role="menuitemradio"]')[1]!.attributes('aria-checked')).toBe('true')
  await wrapper.get('[role="menu"]').trigger('keydown', { key: 'Escape' })
  expect(wrapper.find('[role="menu"]').exists()).toBe(false)
  await wrapper.get('.sidebar-language__trigger').trigger('click')
  await flushPromises()
  document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
  await flushPromises()
  expect(wrapper.find('[role="menu"]').exists()).toBe(false)
  expect(api.updateGeneralConfig).toHaveBeenCalledOnce()
})

it('keeps current language on load failure and allows retry', async () => {
  vi.mocked(api.generalConfig).mockRejectedValueOnce(new Error('load failed'))
  const wrapper = render()
  await wrapper.get('.sidebar-language__trigger').trigger('click')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toBe('load failed')
  expect(wrapper.findAll('[role="menuitemradio"]').every(radio => radio.attributes('disabled') !== undefined)).toBe(true)
  await wrapper.get('.app-button--secondary').trigger('click')
  await flushPromises()
  expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  expect(api.generalConfig).toHaveBeenCalledTimes(2)
})

it('blocks duplicate submissions while saving and allows retry after failure', async () => {
  let rejectSave!: (error: Error) => void
  vi.mocked(api.updateGeneralConfig).mockReturnValueOnce(new Promise((_, reject) => { rejectSave = reject }))
  const wrapper = render()
  await wrapper.get('.sidebar-language__trigger').trigger('click')
  await flushPromises()
  await wrapper.findAll('[role="menuitemradio"]')[1]!.trigger('click')
  expect(locale.value).toBe('en')
  await wrapper.get('.sidebar-language__trigger').trigger('click')
  expect(wrapper.find('[role="menu"]').exists()).toBe(false)
  expect(api.updateGeneralConfig).toHaveBeenCalledOnce()
  rejectSave(new Error('save failed'))
  await flushPromises()
  expect(notice.error).toHaveBeenCalledWith('save failed')
  expect(locale.value).toBe('zh')
  await wrapper.get('.sidebar-language__trigger').trigger('click')
  await flushPromises()
  await wrapper.findAll('[role="menuitemradio"]')[1]!.trigger('click')
  await flushPromises()
  expect(locale.value).toBe('en')
})

it('displays loading state and supports workflow surfaces without a theme toggle', async () => {
  vi.mocked(api.generalConfig).mockReturnValueOnce(new Promise(() => {}))
  const wrapper = render(true, false)
  await wrapper.get('.sidebar-language__trigger').trigger('click')
  expect(wrapper.get('[role="status"]').text()).toBe('加载中…')
  expect(wrapper.find('.app-button--primary').exists()).toBe(false)
  expect(wrapper.find('.app-theme-toggle').exists()).toBe(false)
})

it('does not write again when the current language is selected', async () => {
  const wrapper = render()
  await wrapper.get('.sidebar-language__trigger').trigger('click')
  await flushPromises()
  await wrapper.findAll('[role="menuitemradio"]')[0]!.trigger('click')
  expect(api.updateGeneralConfig).not.toHaveBeenCalled()
  expect(locale.value).toBe('zh')
  expect(wrapper.find('[role="menu"]').exists()).toBe(false)
})

it('ignores a pending language load after the preferences are unmounted', async () => {
  let finish!: (response: Awaited<ReturnType<typeof api.generalConfig>>) => void
  vi.mocked(api.generalConfig).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
  const wrapper = render()
  await wrapper.get('.sidebar-language__trigger').trigger('click')
  wrapper.unmount()
  applySavedLocale('en')
  finish({ code: 0, message: '', data: { id: 1, created_at: '', updated_at: '', prompt_language: 'zh' } })
  await flushPromises()
  expect(locale.value).toBe('en')
})

it('ignores an older load after the panel has been reopened', async () => {
  let finish!: (response: Awaited<ReturnType<typeof api.generalConfig>>) => void
  vi.mocked(api.generalConfig).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
  const wrapper = render()
  await wrapper.get('.sidebar-language__trigger').trigger('click')
  await wrapper.get('[role="menu"]').trigger('keydown', { key: 'Escape' })
  await wrapper.get('.sidebar-language__trigger').trigger('click')
  await flushPromises()
  finish({ code: 0, message: '', data: { id: 1, created_at: '', updated_at: '', prompt_language: 'en' } })
  await flushPromises()
  expect(wrapper.findAll('[role="menuitemradio"]')[0]!.attributes('aria-checked')).toBe('true')
  expect(locale.value).toBe('zh')
})
