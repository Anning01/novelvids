import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, expect, it, vi } from 'vitest'
import LoginPage from './LoginPage.vue'
import QilingLogin from '@/features/auth/QilingLogin.vue'
import { useAuthStore } from '@/features/auth/authStore'

async function mountPage(enabled = true, redirect = '/', options: { provider?: 'password' | 'qiling'; registrationEnabled?: boolean; path?: string } = {}) {
  const pinia = createPinia()
  const auth = useAuthStore(pinia)
  auth.$patch({ enabled: true, provider: options.provider ?? 'qiling', legalReady: true, qilingEnabled: enabled,
    registrationEnabled: options.registrationEnabled ?? false })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/login', component: LoginPage },
      { path: '/register', component: LoginPage },
      { path: '/', component: { template: '<div />' } },
      { path: '/invite/:token', component: { template: '<div />' } },
      { path: '/projects', component: { template: '<div />' } },
    ],
  })
  await router.push({ path: options.path ?? '/login', query: { redirect } })
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

it('lets users pause the background video while filling in account details', async () => {
  const pause = vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined)
  const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
  const { wrapper } = await mountPage()
  await wrapper.get('button[aria-label="暂停背景动画"]').trigger('click')
  expect(pause).toHaveBeenCalledOnce()
  expect(wrapper.get('video').attributes('autoplay')).toBeUndefined()
  await wrapper.get('button[aria-label="播放背景动画"]').trigger('click')
  expect(play).toHaveBeenCalledOnce()
  expect(wrapper.get('video').attributes('autoplay')).toBeDefined()
  pause.mockRestore()
  play.mockRestore()
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

it('switches between password login and registration while keeping the destination and username', async () => {
  const { wrapper, router } = await mountPage(true, '/projects', { provider: 'password', registrationEnabled: true })
  await wrapper.get('input[autocomplete="username"]').setValue('小影')
  await wrapper.get('input[autocomplete="current-password"]').setValue('old-password')
  await wrapper.get('[data-mode="register"]').trigger('click')
  await flushPromises()
  expect(router.currentRoute.value.path).toBe('/register')
  expect(router.currentRoute.value.query.redirect).toBe('/projects')
  expect(wrapper.get('h2').text()).toBe('创建账号')
  expect(wrapper.get<HTMLInputElement>('input[autocomplete="username"]').element.value).toBe('小影')
  expect(wrapper.get<HTMLInputElement>('input[autocomplete="new-password"]').element.value).toBe('')
  expect(wrapper.get('input[autocomplete="new-password"]').attributes('minlength')).toBe('8')
  expect(wrapper.get('[data-mode="register"]').attributes('aria-pressed')).toBe('true')
  await wrapper.get('[data-mode="login"]').trigger('click')
  await flushPromises()
  expect(wrapper.find('input[autocomplete="nickname"]').exists()).toBe(false)
  expect(wrapper.find('input[autocomplete="current-password"]').exists()).toBe(true)
})

it('registers an ordinary account without an invite then continues to the destination', async () => {
  const { wrapper, auth, router } = await mountPage(true, '/projects', { provider: 'password', registrationEnabled: true, path: '/register' })
  const register = vi.spyOn(auth, 'register').mockResolvedValue()
  await wrapper.get('input[autocomplete="username"]').setValue(' new-creator ')
  await wrapper.get('input[autocomplete="nickname"]').setValue(' 小影 ')
  await wrapper.get('input[autocomplete="new-password"]').setValue('password123')
  await wrapper.get('input[type="checkbox"]').setValue(true)
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(register).toHaveBeenCalledWith({ username: 'new-creator', nickname: '小影', password: 'password123' })
  expect(router.currentRoute.value.path).toBe('/projects')
})

it('can reveal a registration password without submitting the form', async () => {
  const { wrapper, auth } = await mountPage(true, '/', { provider: 'password', registrationEnabled: true, path: '/register' })
  const register = vi.spyOn(auth, 'register').mockResolvedValue()
  await wrapper.get('input[autocomplete="new-password"]').setValue('password123')
  await wrapper.get('button[aria-label="显示密码"]').trigger('click')
  expect(wrapper.get('input[autocomplete="new-password"]').attributes('type')).toBe('text')
  await wrapper.get('button[aria-label="隐藏密码"]').trigger('click')
  expect(wrapper.get('input[autocomplete="new-password"]').attributes('type')).toBe('password')
  expect(register).not.toHaveBeenCalled()
})

it('shows registration failures and keeps the entered account details', async () => {
  const { wrapper, auth } = await mountPage(true, '/', { provider: 'password', registrationEnabled: true, path: '/register' })
  vi.spyOn(auth, 'register').mockRejectedValue(new Error('用户名已被使用'))
  await wrapper.get('input[autocomplete="username"]').setValue('taken')
  await wrapper.get('input[autocomplete="new-password"]').setValue('password123')
  await wrapper.get('input[type="checkbox"]').setValue(true)
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('用户名已被使用')
  expect(wrapper.get<HTMLInputElement>('input[autocomplete="username"]').element.value).toBe('taken')
  expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeUndefined()
})

it('does not submit short passwords or bypass the legal checkbox', async () => {
  const { wrapper, auth } = await mountPage(true, '/', { provider: 'password', registrationEnabled: true, path: '/register' })
  const register = vi.spyOn(auth, 'register').mockResolvedValue()
  await wrapper.get('input[autocomplete="username"]').setValue('new-user')
  await wrapper.get('input[autocomplete="new-password"]').setValue('short')
  await wrapper.get('form').trigger('submit')
  expect(register).not.toHaveBeenCalled()
  await wrapper.get('input[autocomplete="new-password"]').setValue('password123')
  await wrapper.get('form').trigger('submit')
  expect(register).not.toHaveBeenCalled()
})

it('redirects a disabled registration page to password login', async () => {
  const { wrapper, router } = await mountPage(true, '/projects', { provider: 'password', path: '/register' })
  await flushPromises()
  expect(router.currentRoute.value.path).toBe('/login')
  expect(wrapper.find('[data-mode="register"]').exists()).toBe(false)
  expect(wrapper.find('input[autocomplete="new-password"]').exists()).toBe(false)
})

it('prevents duplicate registration and mode changes while the request is running', async () => {
  const { wrapper, auth } = await mountPage(true, '/', { provider: 'password', registrationEnabled: true, path: '/register' })
  let finish: (() => void) | undefined
  const register = vi.spyOn(auth, 'register').mockImplementation(() => new Promise<void>(resolve => { finish = resolve }))
  await wrapper.get('input[autocomplete="username"]').setValue('new-user')
  await wrapper.get('input[autocomplete="new-password"]').setValue('password123')
  await wrapper.get('input[type="checkbox"]').setValue(true)
  await wrapper.get('form').trigger('submit')
  await wrapper.get('form').trigger('submit')
  expect(register).toHaveBeenCalledOnce()
  expect(wrapper.get('[data-mode="login"]').attributes('disabled')).toBeDefined()
  expect(wrapper.get('button[type="submit"]').attributes('aria-busy')).toBe('true')
  finish?.()
  await flushPromises()
})
