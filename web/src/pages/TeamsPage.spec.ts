import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import TeamsPage from './TeamsPage.vue'
import { api } from '@/api'

function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/teams', component: TeamsPage }],
  })
  return mount(TeamsPage, { global: { plugins: [createPinia(), router] } })
}

describe('TeamsPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('renders teams with member limit and overdraft highlight', async () => {
    vi.spyOn(api, 'teams').mockResolvedValue({
      data: {
        items: [
          { id: 1, name: '健康队', balance: 12.5, model_config_source: 'official', status: 1, member_limit: 5, member_count: 3 },
          { id: 2, name: '欠费队', balance: -3, model_config_source: 'custom', status: 1, member_limit: null, member_count: 1 },
        ],
        pagination: { total: 2, page: 1, page_size: 100, pages: 1 },
      },
    } as never)

    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('健康队')
    expect(wrapper.text()).toContain('欠费队')
    expect(wrapper.text()).toContain('5')
    expect(wrapper.text()).toContain('不限')
    const overdraft = wrapper.findAll('.is-overdraft')
    expect(overdraft).toHaveLength(1)
    expect(overdraft[0].text()).toContain('-3.00')
  })

  it('creates team through dialog with required owner', async () => {
    vi.spyOn(api, 'teams').mockResolvedValue({
      data: { items: [], pagination: { total: 0, page: 1, page_size: 100, pages: 0 } },
    } as never)
    vi.spyOn(api, 'users').mockResolvedValue({
      data: {
        items: [
          { id: 7, username: 'owner7', nickname: '七号', is_super_admin: false, status: 1, total_cost: '0.000000', team_count: 0 },
          { id: 8, username: 'boss8', nickname: '', is_super_admin: true, status: 1, total_cost: '0.000000', team_count: 0 },
        ],
        pagination: { total: 2, page: 1, page_size: 100, pages: 1 },
      },
    } as never)
    vi.spyOn(api, 'createTeam').mockResolvedValue({
      data: { id: 5, name: '新队', balance: 0, model_config_source: 'official', status: 1, member_limit: 8, owner_user_id: 7, owner_username: 'owner7', member_count: 1 },
    } as never)

    const wrapper = mountPage()
    await flushPromises()
    // 列表页上不再有内联创建表单
    expect(wrapper.find('.page-header form').exists()).toBe(false)

    const openButton = wrapper.findAll('button').find(button => button.text() === '新建团队')
    await openButton!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.dialog-card').exists()).toBe(true)

    // 所有人选择器：AppSelect，包含超管（带标识），默认选中第一个普通用户
    const ownerTrigger = wrapper.find('.dialog-card .app-select__trigger')
    expect(ownerTrigger.exists()).toBe(true)
    expect(ownerTrigger.text()).toContain('owner7')
    expect(ownerTrigger.text()).toContain('七号')

    await ownerTrigger.trigger('click')
    const options = document.querySelectorAll('.app-select__menu .app-select__option')
    expect(options).toHaveLength(2)
    expect(options[0].textContent).toContain('owner7')
    expect(options[1].textContent).toContain('boss8')
    expect(options[1].textContent).toContain('超管')

    const inputs = wrapper.findAll('.dialog-card input')
    await inputs[0].setValue('新队')
    await inputs[1].setValue('8')
    await wrapper.get('.dialog-card').trigger('submit')
    await flushPromises()

    expect(api.createTeam).toHaveBeenCalledWith({ name: '新队', owner_user_id: 7, member_limit: 8 })
  })

  it('tops up a team via api', async () => {
    vi.spyOn(api, 'teams').mockResolvedValue({
      data: {
        items: [{ id: 1, name: '健康队', balance: 0, model_config_source: 'official', status: 1, member_limit: null, member_count: 0 }],
        pagination: { total: 1, page: 1, page_size: 100, pages: 1 },
      },
    } as never)
    vi.spyOn(api, 'teamTopUp').mockResolvedValue({
      data: { team_id: 1, balance: 50 },
    } as never)
    vi.spyOn(window, 'prompt').mockReturnValue('50')

    const wrapper = mountPage()
    await flushPromises()
    const buttons = wrapper.findAll('button')
    const topUpButton = buttons.find(button => button.text() === '充值')
    expect(topUpButton).toBeTruthy()
    await topUpButton!.trigger('click')
    await flushPromises()

    expect(api.teamTopUp).toHaveBeenCalledWith({ team_id: 1, amount: 50, note: '管理端充值' })
  })
})
