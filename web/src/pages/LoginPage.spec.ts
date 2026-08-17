import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import LoginPage from './LoginPage.vue'
import { api } from '@/api'
import { useAuthStore } from '@/features/auth/authStore'

function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/login', component: LoginPage },
      { path: '/', component: { template: '<div />' } },
    ],
  })
  return mount(LoginPage, {
    global: { plugins: [createPinia(), router] },
  })
}

describe('LoginPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('renders the login form', () => {
    const wrapper = mountPage()
    expect(wrapper.get('h1').text()).toBe('登录')
    expect(wrapper.find('input[type="text"]').element).toBeInstanceOf(HTMLInputElement)
    expect(wrapper.find('input[type="password"]').element).toBeInstanceOf(HTMLInputElement)
  })

  it('shows validation error for empty fields', async () => {
    const wrapper = mountPage()
    await wrapper.get('form').trigger('submit')
    expect(wrapper.get('[role="alert"]').text()).toContain('请输入用户名和密码')
  })

  it('logs in and redirects on success', async () => {
    vi.spyOn(api, 'login').mockResolvedValue({
      data: { token: 't1', user: { id: 1, username: 'alice', nickname: '爱丽丝', avatar_url: '', is_super_admin: false } },
    } as never)
    vi.spyOn(api, 'me').mockResolvedValue({
      data: { user: { id: 1, username: 'alice', nickname: '爱丽丝', avatar_url: '', is_super_admin: false }, memberships: [] },
    } as never)

    const wrapper = mountPage()
    await wrapper.get('input[type="text"]').setValue('  alice  ')
    await wrapper.get('input[type="password"]').setValue('password123')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(api.login).toHaveBeenCalledWith('alice', 'password123')
    const store = useAuthStore()
    expect(store.token).toBe('t1')
  })

  it('shows backend error message on failure', async () => {
    vi.spyOn(api, 'login').mockRejectedValue(new Error('用户名或密码错误'))
    const wrapper = mountPage()
    await wrapper.get('input[type="text"]').setValue('alice')
    await wrapper.get('input[type="password"]').setValue('bad')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('用户名或密码错误')
  })
})
