import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import App from './App.vue'
import { useAuthStore } from '@/features/auth/authStore'
import { setLocale } from '@/i18n'

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

  it.each(['admin', 'creator', 'viewer'])('开放平台模型配置入口仅超管可见，当前团队角色为 %s', role => {
    const pinia = setupStore({enabled:true, ready:true, token:'t', deploymentRole:'platform',
      user:{id:9, username:'user', nickname:'用户', is_super_admin:false},
      memberships:[{team_id:1,team_name:'团队',role}], activeTeamId:1})
    const wrapper = mountApp(pinia)
    expect(wrapper.find('a[href$="/settings"]').exists()).toBe(false)
    expect(wrapper.find('a[href$="/projects"]').exists()).toBe(false)
    useAuthStore(pinia).user!.is_super_admin = true
    return wrapper.vm.$nextTick().then(() => {
      expect(wrapper.find('a[href$="/settings"]').exists()).toBe(true)
      wrapper.unmount()
    })
  })

  it('translates all shared navigation when switching languages in place', async () => {
    const wrapper = mountApp(setupStore({ enabled: true, ready: true, token: 't',
      user: { id: 1, username: 'admin', nickname: '保留用户昵称', is_super_admin: true },
      memberships: [], activeTeamId: null }))
    setLocale('en')
    await wrapper.vm.$nextTick()
    expect(wrapper.get('a[href="/projects"]').text()).toBe('My creations')
    expect(wrapper.get('a[href="/orders"]').text()).toBe('Order management')
    expect(wrapper.get('nav').text()).not.toMatch(/[\u4e00-\u9fff]/)
    expect(wrapper.get('.app-user-name').text()).toBe('保留用户昵称')
    setLocale('zh')
    await wrapper.vm.$nextTick()
    expect(wrapper.get('a[href="/projects"]').text()).toBe('我的创作')
    wrapper.unmount()
  })

  it('侧边栏同步展示新头像，图片失败时回退到昵称首字', async () => {
    const pinia = setupStore({enabled:true,ready:true,token:'t',
      user:{id:1,username:'user',nickname:'小新',avatar_url:'/media/avatar.png',is_super_admin:false},
      memberships:[{team_id:1,team_name:'团队',role:'creator'}],activeTeamId:1})
    const wrapper = mountApp(pinia)
    expect(wrapper.get('.app-user-avatar img').attributes('src')).toBe('/media/avatar.png')
    await wrapper.get('.app-user-avatar img').trigger('error')
    expect(wrapper.get('.app-user-avatar').text()).toBe('小')
    useAuthStore(pinia).user!.avatar_url='/media/new.png'
    await wrapper.vm.$nextTick()
    expect(wrapper.get('.app-user-avatar img').attributes('src')).toBe('/media/new.png')
    wrapper.unmount()
  })

  it('vanilla（未开启登录）时不显示团队选择器，保留外观按钮', () => {
    const wrapper = mountApp(setupStore({ enabled: false, ready: true }))
    expect(wrapper.find('.app-team-selector').exists()).toBe(false)
    expect(wrapper.find('.app-user-block').exists()).toBe(false)
    expect(wrapper.find('.app-theme-toggle.is-sidebar').exists()).toBe(true)
  })

  it('多团队成员的登录用户在 Logo 下方显示团队选择器', async () => {
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
    const trigger = wrapper.get('button[aria-label="切换团队"]')
    expect(trigger.text()).toBe('乙队')
    expect(wrapper.find('select').exists()).toBe(false)
    wrapper.get('.app-team-selector').element.getBoundingClientRect = () => new DOMRect(10, 50, 172, 34)
    await trigger.trigger('click')
    const menu = document.querySelector<HTMLElement>('[role="listbox"][aria-label="切换团队"]')!
    expect(menu.style.width).toBe('172px')
    const options = Array.from(document.querySelectorAll('[role="listbox"][aria-label="切换团队"] [role="option"]'))
    expect(options.map(option => option.textContent?.trim())).toEqual(['甲队', '乙队'])
    expect(options[1]?.getAttribute('aria-selected')).toBe('true')
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
    expect(wrapper.find('button[aria-label="切换团队"]').exists()).toBe(false)
  })

  it.each(['light', 'dark'])('超管在普通成员团队中隐藏无权进入的管理入口（%s）', async theme => {
    document.documentElement.dataset.appTheme = theme
    const pinia = setupStore({
      enabled: true, ready: true, token: 't',
      user: { id: 9, username: 'boss', nickname: '', avatar_url: '', is_super_admin: true },
      memberships: [{ team_id: 1, team_name: '成员团队', role: 'creator' }], activeTeamId: 1,
    })
    const wrapper = mountApp(pinia)
    for (const path of ['/settings', '/teams', '/users', '/members']) {
      expect(wrapper.find(`a[href$="${path}"]`).exists()).toBe(false)
    }
    const auth = useAuthStore(pinia)
    auth.setActiveTeam(null)
    await wrapper.vm.$nextTick()
    for (const path of ['/settings', '/teams', '/users']) {
      expect(wrapper.find(`a[href$="${path}"]`).exists()).toBe(true)
    }
    wrapper.unmount()
    delete document.documentElement.dataset.appTheme
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

  it('左下角用户入口按角色显示限额或余额', async () => {
    // 团队管理员 → 团队余额
    let wrapper = mountApp(setupStore({
      enabled: true,
      token: 't',
      user: { id: 1, username: 'boss', nickname: '', avatar_url: '', is_super_admin: false },
      memberships: [{ team_id: 1, team_name: '甲队', role: 'admin', team_balance: '123.45' }],
      activeTeamId: 1,
    }))
    expect(wrapper.find('.app-user-wallet').text()).toBe('余额 ¥123.45')

    // 创作者有限额 → 显示限额
    wrapper = mountApp(setupStore({
      enabled: true,
      token: 't',
      user: { id: 2, username: 'c', nickname: '', avatar_url: '', is_super_admin: false },
      memberships: [{ team_id: 1, team_name: '甲队', role: 'creator', cost_limit: '50', team_balance: '999' }],
      activeTeamId: 1,
    }))
    expect(wrapper.find('.app-user-wallet').text()).toBe('限额 ¥50.00')

    // 创作者不限 → 显示团队余额
    wrapper = mountApp(setupStore({
      enabled: true,
      token: 't',
      user: { id: 3, username: 'c2', nickname: '', avatar_url: '', is_super_admin: false },
      memberships: [{ team_id: 1, team_name: '甲队', role: 'viewer', cost_limit: null, team_balance: '88' }],
      activeTeamId: 1,
    }))
    expect(wrapper.find('.app-user-wallet').text()).toBe('余额 ¥88.00')

    // 超管不显示
    wrapper = mountApp(setupStore({
      enabled: true,
      token: 't',
      user: { id: 9, username: 'boss', nickname: '', avatar_url: '', is_super_admin: true },
      memberships: [],
      activeTeamId: null,
    }))
    expect(wrapper.find('.app-user-wallet').exists()).toBe(false)
  })
