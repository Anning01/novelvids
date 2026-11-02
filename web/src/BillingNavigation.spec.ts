import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import App from './App.vue'
import AppButton from '@/components/AppButton.vue'
import router from './router'
import { api } from '@/api'
import { setLocale } from '@/i18n'
import { useAuthStore } from '@/features/auth/authStore'

vi.mock('@/api', async importOriginal => {
  const original = await importOriginal<typeof import('@/api')>()
  return { ...original, api: { ...original.api, billingSummary: vi.fn(), billingProjects: vi.fn(), billingRecords: vi.fn() } }
})

beforeEach(() => {
  localStorage.clear()
  setLocale('zh')
  vi.clearAllMocks()
  vi.mocked(api.billingSummary).mockResolvedValue({ code: 0, message: 'ok', data: {
    total_cost: 1.25, total_records: 1, by_billing_type: [], by_task_type: [], by_model: [], daily_trend: [],
  } })
  vi.mocked(api.billingProjects).mockResolvedValue({ code: 0, message: 'ok', data: {
    items: [], pagination: { page: 1, page_size: 100, total: 0, pages: 0 },
  } })
  vi.mocked(api.billingRecords).mockResolvedValue({ code: 0, message: 'ok', data: {
    items: [], pagination: { page: 1, page_size: 20, total: 0, pages: 0 },
  } })
})

async function render(role: 'creator' | 'viewer') {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().$patch({
    enabled: true, ready: true, token: 'test-session',
    user: { id: 1, username: 'creator', nickname: '创作者', avatar_url: '', is_super_admin: false },
    memberships: [{ team_id: 1, team_name: '测试团队', role }], activeTeamId: 1,
  })
  await router.push('/')
  const wrapper = mount(App, { global: { plugins: [pinia, router], components: { AppButton } } })
  await router.isReady()
  await flushPromises()
  return wrapper
}

it('opens the real billing route and page when a creator clicks the cost menu', async () => {
  const wrapper = await render('creator')
  await wrapper.get('a[aria-label="成本"]').trigger('click')
  await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/billing'))
  await flushPromises()
  expect(router.currentRoute.value.path).toBe('/billing')
  expect(wrapper.get('.billing-page').text()).toContain('成本看板')
  expect(wrapper.get('.billing-page').text()).toContain('¥1.25')
  expect(api.billingSummary).toHaveBeenCalledOnce()
  expect(wrapper.get('a[aria-label="成本"]').classes()).toContain('is-active')
  wrapper.unmount()
})

it('keeps billing hidden and blocks direct navigation for a viewer', async () => {
  const wrapper = await render('viewer')
  expect(wrapper.find('a[aria-label="成本"]').exists()).toBe(false)
  await router.push('/billing')
  await flushPromises()
  expect(router.currentRoute.value.path).toBe('/')
  expect(wrapper.find('.billing-page').exists()).toBe(false)
  expect(api.billingSummary).not.toHaveBeenCalled()
  wrapper.unmount()
})
