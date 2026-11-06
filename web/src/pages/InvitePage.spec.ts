import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import InvitePage from './InvitePage.vue'
import { api } from '@/api'
import { useAuthStore } from '@/features/auth/authStore'

async function mountPage(pinia: Pinia, token: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/invite/:token', component: InvitePage }, { path: '/login', component: { template: '<div />' } }],
  })
  await router.push(`/invite/${token}`)
  await router.isReady()
  return mount(InvitePage, { global: { plugins: [pinia, router] } })
}

describe('InvitePage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('shows team info and lets logged-in user join', async () => {
    vi.spyOn(api, 'teamInviteInfo').mockResolvedValue({
      data: { token: 't1', team_id: 1, team_name: '邀请团队', role: 'creator', expires_at: '' },
    } as never)
    vi.spyOn(api, 'joinTeamInvite').mockResolvedValue({ data: {} } as never)

    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useAuthStore(pinia)
    store.$patch({
      enabled: true,
      token: 'session',
      user: { id: 1, username: 'u', nickname: '', avatar_url: '', is_super_admin: false },
      memberships: [],
    })

    const wrapper = await mountPage(pinia, 't1')
    await flushPromises()
    expect(wrapper.text()).toContain('邀请团队')

    const joinButton = wrapper.findAll('button').find(button => button.text().includes('加入团队'))
    await joinButton!.trigger('click')
    await flushPromises()
    expect(api.joinTeamInvite).toHaveBeenCalledWith('t1')
  })

  it('sends a signed-out invitee through Qiling login and back to the same invitation', async () => {
    vi.spyOn(api, 'teamInviteInfo').mockResolvedValue({
      data: { token: 't2', team_id: 2, team_name: '注册团队', role: 'viewer', expires_at: '' },
    } as never)
    const pinia = createPinia()
    useAuthStore(pinia).$patch({ provider: 'qiling' })
    const wrapper = await mountPage(pinia, 't2')
    await flushPromises()
    expect(wrapper.get('a').attributes('href')).toContain('/login?redirect=/invite/t2')
    expect(wrapper.find('form').exists()).toBe(false)
  })

  it('shows error for invalid invite', async () => {
    vi.spyOn(api, 'teamInviteInfo').mockRejectedValue(new Error('邀请链接不存在或已过期'))
    const pinia = createPinia()
    setActivePinia(pinia)
    const wrapper = await mountPage(pinia, 'bad-token')
    await flushPromises()
    expect(wrapper.text()).toContain('邀请无效')
  })
})
