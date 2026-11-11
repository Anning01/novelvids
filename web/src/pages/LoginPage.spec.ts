import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, expect, it, vi } from 'vitest'
import LoginPage from './LoginPage.vue'
import QilingLogin from '@/features/auth/QilingLogin.vue'
import { useAuthStore } from '@/features/auth/authStore'

async function mountPage(enabled = true, redirect = '/') {
  const pinia = createPinia()
  const auth = useAuthStore(pinia)
  auth.$patch({ enabled: true, provider: 'qiling', legalReady: true, qilingEnabled: enabled })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/login', component: LoginPage },
      { path: '/', component: { template: '<div />' } },
      { path: '/invite/:token', component: { template: '<div />' } },
    ],
  })
  await router.push({ path: '/login', query: { redirect } })
  const wrapper = mount(LoginPage, { global: { plugins: [pinia, router], stubs: { QilingLogin: true } } })
  return { wrapper, auth, router }
}

afterEach(() => vi.unstubAllGlobals())

it.each(['light', 'dark'])('shows a glass sign-in card with only Qiling login in %s mode', async theme => {
  document.documentElement.dataset.appTheme = theme
  try {
    const { wrapper } = await mountPage()
    expect(wrapper.get('.cinematic-login__glass').text()).toContain('微信扫码登录')
    expect(wrapper.findComponent(QilingLogin).exists()).toBe(false)
    expect(wrapper.get('a[href="/api/auth/legal/terms"]').text()).toBe('用户协议')
    expect(wrapper.get('a[href="/api/auth/legal/privacy"]').text()).toBe('隐私政策')
    await wrapper.get('input[type="checkbox"]').setValue(true)
    expect(wrapper.getComponent(QilingLogin).props('autoStart')).toBe(true)
    expect(wrapper.find('input[type="password"]').exists()).toBe(false)
    expect(wrapper.get('video').attributes('src')).toMatch(/static\/bg\.mp4$/)
  } finally {
    delete document.documentElement.dataset.appTheme
  }
})

it('uses a static background when reduced motion is requested', async () => {
  vi.stubGlobal('matchMedia', () => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
  const { wrapper } = await mountPage()
  expect(wrapper.find('video').exists()).toBe(false)
  expect(wrapper.find('.cinematic-login__motion').exists()).toBe(false)
})

it('continues to the original invitation after sign-in', async () => {
  const { wrapper, auth, router } = await mountPage(true, '/invite/team-token')
  await wrapper.get('input[type="checkbox"]').setValue(true)
  const accept = vi.spyOn(auth, 'acceptSession').mockResolvedValue()
  const session = { token: 'session', user: { id: 1, username: 'alice', nickname: '', avatar_url: '', is_super_admin: false } }
  wrapper.getComponent(QilingLogin).vm.$emit('authenticated', session)
  await flushPromises()
  expect(accept).toHaveBeenCalledWith(session)
  expect(router.currentRoute.value.path).toBe('/invite/team-token')
})

it('explains when the only sign-in provider is unavailable', async () => {
  const { wrapper } = await mountPage(false)
  expect(wrapper.get('[role="alert"]').text()).toContain('器灵登录暂不可用')
  expect(wrapper.findComponent(QilingLogin).exists()).toBe(false)
})

it('shows account/password login when password login is enabled and does not mount Qiling', async () => {
  const { wrapper, auth } = await mountPage()
  auth.$patch({ provider: 'password', qilingEnabled: false, legalReady: false })
  await flushPromises()
  expect(wrapper.get('h2').text()).toBe('账号登录')
  expect(wrapper.findComponent(QilingLogin).exists()).toBe(false)
  expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false)
  const login = vi.spyOn(auth, 'login').mockResolvedValue()
  await wrapper.get('input[autocomplete="username"]').setValue(' local-admin ')
  await wrapper.get('input[type="password"]').setValue('local-password')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(login).toHaveBeenCalledWith('local-admin', 'local-password')
})

it('does not allow accepting an incomplete legal notice when Qiling login is enabled', async () => {
  const { wrapper, auth } = await mountPage()
  auth.$patch({ legalReady: false })
  await flushPromises()
  expect(wrapper.text()).toContain('运营者尚未完善协议配置')
  expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false)
  expect(wrapper.findComponent(QilingLogin).exists()).toBe(false)
})
