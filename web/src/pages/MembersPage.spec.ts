import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import MembersPage from './MembersPage.vue'
import { api } from '@/api'
import { useAuthStore } from '@/features/auth/authStore'

function mountPage(pinia: Pinia) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/members', component: MembersPage }],
  })
  return mount(MembersPage, { global: { plugins: [pinia, router] } })
}

function setupStore() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useAuthStore(pinia)
  store.$patch({
    enabled: true,
    user: { id: 1, username: 'admin', nickname: '管理员', avatar_url: '', is_super_admin: false },
    memberships: [{ team_id: 9, team_name: 'A队', role: 'admin' }],
    activeTeamId: 9,
  })
  return pinia
}

describe('MembersPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('renders members with cost/limit columns and no creation form', async () => {
    vi.spyOn(api, 'teamMembers').mockResolvedValue({
      data: {
        items: [
          { user_id: 2, username: 'bob', nickname: '鲍勃', role: 'creator', status: 1, total_cost: '12.340000', cost_limit: '100.000000' },
        ],
        pagination: { total: 1, page: 1, page_size: 20, pages: 1 },
      },
    } as never)

    const wrapper = mountPage(setupStore())
    await flushPromises()
    expect(wrapper.text()).toContain('bob')
    expect(wrapper.text()).toContain('12.34')
    expect(wrapper.text()).toContain('100.00')
    expect(wrapper.text()).toContain('邀请成员')
    expect(wrapper.text()).not.toContain('创建成员')
  })

  it('creates invite link with selected role', async () => {
    vi.spyOn(api, 'teamMembers').mockResolvedValue({
      data: { items: [], pagination: { total: 0, page: 1, page_size: 20, pages: 0 } },
    } as never)
    vi.spyOn(api, 'createTeamInvite').mockResolvedValue({
      data: { token: 'invite-token-1', team_id: 9, team_name: 'A队', role: 'viewer', expires_at: '' },
    } as never)

    const wrapper = mountPage(setupStore())
    await flushPromises()

    const roleSelect = wrapper.find('section.panel select')
    await roleSelect.setValue('viewer')
    const buttons = wrapper.findAll('button')
    const inviteButton = buttons.find(button => button.text().includes('生成邀请链接'))
    expect(inviteButton).toBeTruthy()
    await inviteButton!.trigger('click')
    await flushPromises()

    expect(api.createTeamInvite).toHaveBeenCalledWith('viewer', 9)
    const linkInput = wrapper.find('.invite-link-row input').element as HTMLInputElement
    expect(linkInput.value).toContain('invite-token-1')
  })

  it('disables member and sets limit via api', async () => {
    vi.spyOn(api, 'teamMembers').mockResolvedValue({
      data: {
        items: [{ user_id: 2, username: 'bob', nickname: '鲍勃', role: 'creator', status: 1, total_cost: '0.000000', cost_limit: null }],
        pagination: { total: 1, page: 1, page_size: 20, pages: 1 },
      },
    } as never)
    vi.spyOn(api, 'updateTeamMember').mockResolvedValue({ data: {} } as never)
    vi.spyOn(api, 'setTeamMemberLimit').mockResolvedValue({ data: {} } as never)
    vi.spyOn(window, 'prompt').mockReturnValue('50')

    const wrapper = mountPage(setupStore())
    await flushPromises()

    const buttons = wrapper.findAll('button')
    const disableButton = buttons.find(button => button.text() === '禁用')
    await disableButton!.trigger('click')
    await flushPromises()
    expect(api.updateTeamMember).toHaveBeenCalledWith(2, { status: 0 }, 9)

    const limitButton = buttons.find(button => button.text() === '限额')
    await limitButton!.trigger('click')
    await flushPromises()
    expect(api.setTeamMemberLimit).toHaveBeenCalledWith(2, 50, 9)
  })
})


describe('MembersPage 翻页', () => {
  it('大成员量时按页加载并可翻页', async () => {
    const items = Array.from({ length: 25 }, (_, index) => ({
      user_id: index + 1,
      username: `u${index + 1}`,
      nickname: '',
      role: 'creator',
      status: 1,
      total_cost: '0.000000',
      cost_limit: null,
    }))
    const mock = vi.spyOn(api, 'teamMembers').mockImplementation(async (page = 1) => ({
      data: {
        items: page === 1 ? items.slice(0, 20) : items.slice(20),
        pagination: { total: 25, page, page_size: 20, pages: 2 },
      },
    }) as never)

    const wrapper = mountPage(setupStore())
    await flushPromises()
    expect(wrapper.text()).toContain('成员列表（25）')
    expect(wrapper.text()).toContain('共 25 条')
    expect(wrapper.findAll('tbody tr')).toHaveLength(20)

    const nextButton = wrapper.findAll('.app-pagination button').find(button => button.text() === '下一页')
    await nextButton!.trigger('click')
    await flushPromises()
    expect(mock).toHaveBeenCalledWith(2, 20, 9)
    expect(wrapper.findAll('tbody tr')).toHaveLength(5)
  })
})


describe('MembersPage 本人行不可操作', () => {
  it('管理员本人行禁用操作按钮并显示本人标识', async () => {
    vi.spyOn(api, 'teamMembers').mockResolvedValue({
      data: {
        items: [
          { user_id: 1, username: 'admin', nickname: '管理员', role: 'admin', status: 1, total_cost: '0.000000', cost_limit: null },
          { user_id: 2, username: 'bob', nickname: '鲍勃', role: 'creator', status: 1, total_cost: '0.000000', cost_limit: null },
        ],
        pagination: { total: 2, page: 1, page_size: 20, pages: 1 },
      },
    } as never)

    // setupStore 里 admin 用户 id=1
    const wrapper = mountPage(setupStore())
    await flushPromises()

    const rows = wrapper.findAll('tbody tr')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('本人')
    expect(rows[0].text()).toContain('不可操作本人')
    expect(rows[0].findAll('button')).toHaveLength(0)
    expect(rows[1].findAll('button').length).toBeGreaterThan(0)
  })
})
