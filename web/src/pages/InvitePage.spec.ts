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
    routes: [{ path: '/invite/:token', component: InvitePage }],
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

  it('shows register form for anonymous users', async () => {
    vi.spyOn(api, 'teamInviteInfo').mockResolvedValue({
      data: { token: 't2', team_id: 2, team_name: '注册团队', role: 'viewer', expires_at: '' },
    } as never)
    vi.spyOn(api, 'register').mockResolvedValue({
      data: { token: 'new-session', user: { id: 9, username: 'newbie', nickname: '', avatar_url: '', is_super_admin: false } },
    } as never)
    vi.spyOn(api, 'me').mockResolvedValue({
      data: { user: { id: 9, username: 'newbie', nickname: '', avatar_url: '', is_super_admin: false }, memberships: [{ team_id: 2, team_name: '注册团队', role: 'viewer' }] },
    } as never)

    const pinia = createPinia()
    setActivePinia(pinia)
    const wrapper = await mountPage(pinia, 't2')
    await flushPromises()

    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('newbie')
    await inputs[2].setValue('password-123')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(api.register).toHaveBeenCalledWith(
      expect.objectContaining({ username: 'newbie', invite_token: 't2' }),
    )
    expect(useAuthStore(pinia).token).toBe('new-session')
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
