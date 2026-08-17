import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '@/api'
import { useAuthStore } from './authStore'

function stubApi(overrides: Partial<Record<'authStatus' | 'me' | 'login' | 'logout', () => Promise<unknown>>> = {}) {
  vi.spyOn(api, 'authStatus').mockResolvedValue({ data: { enabled: true } } as never)
  vi.spyOn(api, 'me').mockResolvedValue({ data: { user: { id: 1, username: 'alice', nickname: '爱丽丝', avatar_url: '', is_super_admin: false }, memberships: [{ team_id: 1, team_name: '团队A', role: 'creator' }] } } as never)
  vi.spyOn(api, 'login').mockResolvedValue({ data: { token: 't1', user: { id: 1, username: 'alice', nickname: '爱丽丝', avatar_url: '', is_super_admin: false } } } as never)
  vi.spyOn(api, 'logout').mockResolvedValue({ data: null } as never)
  Object.entries(overrides).forEach(([key, value]) => {
    vi.spyOn(api, key as 'me').mockImplementation(value as never)
  })
}

describe('useAuthStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('bootstrap with auth disabled keeps vanilla access', async () => {
    vi.spyOn(api, 'authStatus').mockResolvedValue({ data: { enabled: false } } as never)
    const store = useAuthStore()
    await store.bootstrap()
    expect(store.enabled).toBe(false)
    expect(store.ready).toBe(true)
    expect(store.isLoggedIn).toBe(false)
    expect(store.canAccessSettings).toBe(true)
    expect(store.canAccessBilling).toBe(true)
  })

  it('bootstrap with auth enabled and stored token loads user', async () => {
    stubApi()
    localStorage.setItem('novelvids_token', 'existing')
    const store = useAuthStore()
    await store.bootstrap()
    expect(store.enabled).toBe(true)
    expect(store.isLoggedIn).toBe(true)
    expect(store.user?.username).toBe('alice')
    expect(store.role).toBe('creator')
    expect(store.canAccessBilling).toBe(true)
    expect(store.canAccessSettings).toBe(false)
  })

  it('bootstrap clears invalid token on 401', async () => {
    stubApi({ me: () => Promise.reject(new Error('未登录')) })
    localStorage.setItem('novelvids_token', 'stale')
    const store = useAuthStore()
    await store.bootstrap()
    expect(store.isLoggedIn).toBe(false)
    expect(localStorage.getItem('novelvids_token')).toBeNull()
  })

  it('login stores token and memberships', async () => {
    stubApi()
    const store = useAuthStore()
    await store.bootstrap()
    await store.login('alice', 'password123')
    expect(store.token).toBe('t1')
    expect(localStorage.getItem('novelvids_token')).toBe('t1')
    expect(store.memberships).toHaveLength(1)
    expect(store.role).toBe('creator')
  })

  it('logout clears state', async () => {
    stubApi()
    const store = useAuthStore()
    await store.bootstrap()
    await store.login('alice', 'password123')
    await store.logout()
    expect(store.token).toBeNull()
    expect(store.user).toBeNull()
    expect(store.isLoggedIn).toBe(false)
    expect(localStorage.getItem('novelvids_token')).toBeNull()
  })

  it('admin role can access settings, viewer cannot', async () => {
    stubApi({
      me: () => Promise.resolve({ data: { user: { id: 2, username: 'bob', nickname: '', avatar_url: '', is_super_admin: false }, memberships: [{ team_id: 1, team_name: '团队A', role: 'admin' }] } } as never),
    })
    localStorage.setItem('novelvids_token', 'admin-token')
    const store = useAuthStore()
    await store.bootstrap()
    expect(store.role).toBe('admin')
    expect(store.canAccessSettings).toBe(true)
    expect(store.canManageMembers).toBe(true)

    stubApi({
      me: () => Promise.resolve({ data: { user: { id: 3, username: 'carol', nickname: '', avatar_url: '', is_super_admin: false }, memberships: [{ team_id: 1, team_name: '团队A', role: 'viewer' }] } } as never),
    })
    const viewerStore = useAuthStore()
    viewerStore.$patch({ ready: false })
    await viewerStore.bootstrap()
    expect(viewerStore.role).toBe('viewer')
    expect(viewerStore.canAccessSettings).toBe(false)
    expect(viewerStore.canAccessBilling).toBe(false)
    expect(viewerStore.canManageMembers).toBe(false)
  })

  it('super admin can access everything', async () => {
    stubApi({
      me: () => Promise.resolve({ data: { user: { id: 9, username: 'boss', nickname: '', avatar_url: '', is_super_admin: true }, memberships: [] } } as never),
    })
    localStorage.setItem('novelvids_token', 'boss-token')
    const store = useAuthStore()
    await store.bootstrap()
    expect(store.role).toBe('super')
    expect(store.canAccessSettings).toBe(true)
    expect(store.canAccessBilling).toBe(true)
    expect(store.canManageTeams).toBe(true)
  })
})
