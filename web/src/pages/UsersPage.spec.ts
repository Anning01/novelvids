import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import UsersPage from './UsersPage.vue'
import { api } from '@/api'

function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/users', component: UsersPage }],
  })
  return mount(UsersPage, { global: { plugins: [createPinia(), router] } })
}

describe('UsersPage 用户管理', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('顶部展示四项统计', async () => {
    vi.spyOn(api, 'userStats').mockResolvedValue({
      data: { user_count: 12, user_total_cost: 345.67, team_count: 3, team_balance_total: 1200.5 },
    } as never)
    vi.spyOn(api, 'users').mockResolvedValue({
      data: { items: [], pagination: { total: 0, page: 1, page_size: 100, pages: 0 } },
    } as never)

    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('用户总数')
    expect(wrapper.text()).toContain('12')
    expect(wrapper.text()).toContain('345.67')
    expect(wrapper.text()).toContain('用户总消耗金额')
    expect(wrapper.text()).toContain('团队总数')
    expect(wrapper.text()).toContain('1200.50')
    expect(wrapper.text()).toContain('团队未消耗总金额')
  })

  it('渲染用户列表并支持禁用登录与删除', async () => {
    vi.spyOn(api, 'userStats').mockResolvedValue({
      data: { user_count: 0, user_total_cost: 0, team_count: 0, team_balance_total: 0 },
    } as never)
    vi.spyOn(api, 'users').mockResolvedValue({
      data: {
        items: [
          { id: 2, username: 'alice', nickname: '爱丽丝', is_super_admin: false, status: 1, created_at: '2026-08-01 10:00:00', total_cost: '5.000000', team_count: 1 },
        ],
        pagination: { total: 1, page: 1, page_size: 100, pages: 1 },
      },
    } as never)
    vi.spyOn(api, 'updateUser').mockResolvedValue({ data: {} } as never)
    vi.spyOn(api, 'deleteUser').mockResolvedValue({ data: null } as never)
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('alice')
    expect(wrapper.text()).toContain('5.00')

    const disableButton = wrapper.findAll('button').find(button => button.text() === '禁用登录')
    await disableButton!.trigger('click')
    await flushPromises()
    expect(api.updateUser).toHaveBeenCalledWith(2, { status: 0 })

    const deleteButton = wrapper.findAll('button').find(button => button.text() === '删除')
    await deleteButton!.trigger('click')
    await flushPromises()
    expect(api.deleteUser).toHaveBeenCalledWith(2)
  })

  it('创建用户走弹窗', async () => {
    vi.spyOn(api, 'userStats').mockResolvedValue({
      data: { user_count: 0, user_total_cost: 0, team_count: 0, team_balance_total: 0 },
    } as never)
    vi.spyOn(api, 'users').mockResolvedValue({
      data: { items: [], pagination: { total: 0, page: 1, page_size: 100, pages: 0 } },
    } as never)
    vi.spyOn(api, 'createUser').mockResolvedValue({
      data: { id: 9, username: 'newbie', nickname: '新人', is_super_admin: false, status: 1, total_cost: '0.000000', team_count: 0 },
    } as never)

    const wrapper = mountPage()
    await flushPromises()

    const openButton = wrapper.findAll('button').find(button => button.text() === '创建用户')
    await openButton!.trigger('click')
    const inputs = wrapper.findAll('.dialog-card input')
    await inputs[0].setValue('newbie')
    await inputs[1].setValue('新人')
    await inputs[2].setValue('newbie-pass-1')
    await wrapper.get('.dialog-card').trigger('submit')
    await flushPromises()

    expect(api.createUser).toHaveBeenCalledWith({ username: 'newbie', nickname: '新人', password: 'newbie-pass-1' })
  })
})
