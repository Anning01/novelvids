import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ProfilePage from './ProfilePage.vue'
import { api } from '@/api'
import { useAuthStore } from '@/features/auth/authStore'

function mountPage(pinia: Pinia) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/profile', component: ProfilePage }],
  })
  return mount(ProfilePage, { global: { plugins: [pinia, router] } })
}

describe('ProfilePage 用户中心', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('展示昵称、历史花费、注册时间与团队信息', async () => {
    vi.spyOn(api, 'me').mockResolvedValue({
      data: {
        user: { id: 1, username: 'alice', nickname: '爱丽丝', avatar_url: '', is_super_admin: false, created_at: '2026-08-01 10:00:00' },
        memberships: [
          { team_id: 1, team_name: '甲队', role: 'admin', status: 1, total_cost: '12.500000', joined_at: '2026-08-02 09:00:00' },
        ],
        is_super_admin: false,
        total_cost: '12.500000',
      },
    } as never)

    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useAuthStore(pinia)
    store.$patch({
      enabled: true,
      token: 't',
      user: { id: 1, username: 'alice', nickname: '爱丽丝', avatar_url: '', is_super_admin: false },
      memberships: [],
    })

    const wrapper = mountPage(pinia)
    await flushPromises()

    expect(wrapper.text()).toContain('爱丽丝')
    expect(wrapper.text()).toContain('12.50')
    expect(wrapper.text()).toContain('2026-08-01 10:00:00')
    expect(wrapper.text()).toContain('甲队')
    expect(wrapper.text()).toContain('团队管理员')
  })

  it('修改密码：两次不一致提示错误', async () => {
    vi.spyOn(api, 'me').mockResolvedValue({
      data: {
        user: { id: 1, username: 'alice', nickname: '爱丽丝', avatar_url: '', is_super_admin: false, created_at: '' },
        memberships: [],
        is_super_admin: false,
        total_cost: 0,
      },
    } as never)
    vi.spyOn(api, 'changePassword').mockResolvedValue({ data: null } as never)

    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useAuthStore(pinia)
    store.$patch({ enabled: true, token: 't', user: { id: 1, username: 'alice', nickname: '', avatar_url: '', is_super_admin: false } })

    const wrapper = mountPage(pinia)
    await flushPromises()

    const inputs = wrapper.findAll('input[type="password"]')
    await inputs[0].setValue('old-pass-1')
    await inputs[1].setValue('new-pass-123')
    await inputs[2].setValue('different-456')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(api.changePassword).not.toHaveBeenCalled()

    await inputs[2].setValue('new-pass-123')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(api.changePassword).toHaveBeenCalledWith('old-pass-1', 'new-pass-123')
  })
})
