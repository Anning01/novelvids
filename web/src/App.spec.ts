import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import App from './App.vue'
import { useAuthStore } from '@/features/auth/authStore'

function mountApp(pinia: Pinia) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div>home</div>' } },
      { path: '/projects', component: { template: '<div>projects</div>' } },
    ],
  })
  return mount(App, {
    global: {
      plugins: [pinia, router],
      stubs: { RouterView: { template: '<div />' } },
    },
  })
}

function setupStore(patch: Record<string, unknown>): Pinia {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useAuthStore(pinia)
  store.$patch(patch)
  return pinia
}

describe('App 侧边栏团队选择器与用户入口', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('vanilla（未开启登录）时不显示团队选择器，保留外观按钮', () => {
    const wrapper = mountApp(setupStore({ enabled: false, ready: true }))
    expect(wrapper.find('.app-team-selector').exists()).toBe(false)
    expect(wrapper.find('.app-user-block').exists()).toBe(false)
    expect(wrapper.find('.app-theme-toggle.is-sidebar').exists()).toBe(true)
  })

  it('多团队成员的登录用户在 Logo 下方显示选择器并可切换', () => {
    const pinia = setupStore({
      enabled: true,
      token: 't',
      user: { id: 1, username: 'u', nickname: '小爱', avatar_url: '', is_super_admin: false },
      memberships: [
        { team_id: 1, team_name: '甲队', role: 'admin' },
        { team_id: 2, team_name: '乙队', role: 'creator' },
      ],
      activeTeamId: 2,
    })
    const wrapper = mountApp(pinia)
    const selector = wrapper.find('.app-team-selector select')
    expect(selector.exists()).toBe(true)
    expect((selector.element as HTMLSelectElement).value).toBe('2')
    const options = selector.findAll('option')
    expect(options).toHaveLength(2)
    expect(options.map(option => option.text())).toEqual(['甲队', '乙队'])
  })

  it('超管（不属于任何团队）显示平台管理员标识', () => {
    const wrapper = mountApp(setupStore({
      enabled: true,
      token: 't',
      user: { id: 9, username: 'boss', nickname: '', avatar_url: '', is_super_admin: true },
      memberships: [],
      activeTeamId: null,
    }))
    expect(wrapper.find('.app-team-selector--super').text()).toContain('平台管理员')
    expect(wrapper.find('.app-team-selector select').exists()).toBe(false)
  })

  it('登录态下用户入口指向用户中心，外观按钮保留在侧边栏', () => {
    const wrapper = mountApp(setupStore({
      enabled: true,
      token: 't',
      user: { id: 1, username: 'u', nickname: '小爱', avatar_url: '', is_super_admin: false },
      memberships: [{ team_id: 1, team_name: '甲队', role: 'admin' }],
      activeTeamId: 1,
    }))
    // 用户入口链接指向用户中心
    const userLink = wrapper.find('.app-user-block')
    expect(userLink.exists()).toBe(true)
    expect(userLink.attributes('href')).toContain('/profile')
    expect(userLink.text()).toContain('小爱')
    // 外观按钮仍在侧边栏（登出已收纳进用户中心，不再拥挤）
    expect(wrapper.find('.app-theme-toggle.is-sidebar').exists()).toBe(true)
  })
})
