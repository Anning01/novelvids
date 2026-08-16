import { defineStore } from 'pinia'
import { api, clearAuthToken, getActiveTeamId, getAuthToken, redirectToLogin, setActiveTeamId, setAuthToken } from '@/api'
import type { AuthUser, Membership, TeamRole } from '@/types'

/**
 * 登录与权限状态。
 *
 * - `enabled === null`：尚未探测（启动时 bootstrap 一次）
 * - `enabled === false`：后端 AUTH_ENABLED=false，保持无鉴权体验（所有权限放行）
 * - `enabled === true`：强制登录，按角色渲染 UI 与守卫路由
 */
export const useAuthStore = defineStore('auth', {
  state: () => ({
    enabled: null as boolean | null,
    ready: false,
    token: getAuthToken(),
    user: null as AuthUser | null,
    memberships: [] as Membership[],
    activeTeamId: getActiveTeamId(),
    totalCost: 0,
  }),
  getters: {
    isLoggedIn: (state) => state.enabled === true && Boolean(state.user && state.token),
    isSuperAdmin: (state) => state.user?.is_super_admin === true,
    membership: (state): Membership | null => (
      state.memberships.find(item => item.team_id === state.activeTeamId)
      ?? state.memberships[0]
      ?? null
    ),
    role: (state): TeamRole | 'super' | null => {
      if (!state.enabled) return null
      if (state.user?.is_super_admin) return 'super'
      const active = state.memberships.find(item => item.team_id === state.activeTeamId) ?? state.memberships[0]
      return active?.role ?? null
    },
    canAccessSettings(): boolean {
      return this.enabled === false || this.role === 'admin' || this.role === 'super'
    },
    canAccessBilling(): boolean {
      return this.enabled === false || this.role === 'admin' || this.role === 'creator' || this.role === 'super'
    },
    canManageMembers(): boolean {
      return this.role === 'admin' || this.role === 'super'
    },
    canManageTeams(): boolean {
      return this.role === 'super'
    },
  },
  actions: {
    async bootstrap(): Promise<void> {
      if (this.ready) return
      try {
        const status = await api.authStatus()
        this.enabled = status.data.enabled
      } catch {
        // 状态探测失败时保守处理：视为未启用，不阻塞应用
        this.enabled = false
      }
      if (this.enabled && this.token) {
        try {
          const me = await api.me()
          this.applyMe(me.data)
        } catch {
          this.token = null
          this.user = null
          clearAuthToken()
        }
      }
      this.ready = true
    },
    applyMe(me: { user: AuthUser; memberships: Membership[]; is_super_admin: boolean; total_cost?: number | string }): void {
      this.user = me.user
      this.memberships = me.memberships
      this.totalCost = Number(me.total_cost ?? 0)
      this.activeTeamId = this._resolveActiveTeam()
    },
    _resolveActiveTeam(): number | null {
      if (!this.memberships.length) return null
      const saved = getActiveTeamId()
      if (saved !== null && this.memberships.some(item => item.team_id === saved)) return saved
      const first = this.memberships[0].team_id
      setActiveTeamId(first)
      return first
    },
    setActiveTeam(teamId: number | null): void {
      setActiveTeamId(teamId)
      this.activeTeamId = teamId
    },
    async login(username: string, password: string): Promise<void> {
      const result = await api.login(username, password)
      setAuthToken(result.data.token)
      this.token = result.data.token
      this.user = result.data.user
      const me = await api.me()
      this.applyMe(me.data)
    },
    async register(data: { username: string; password: string; nickname?: string; invite_token: string }): Promise<void> {
      const result = await api.register(data)
      setAuthToken(result.data.token)
      this.token = result.data.token
      this.user = result.data.user
      const me = await api.me()
      this.applyMe(me.data)
    },
    async refreshMe(): Promise<void> {
      if (!this.token) return
      const me = await api.me()
      this.applyMe(me.data)
    },
    async logout(): Promise<void> {
      try {
        await api.logout()
      } catch {
        // 会话已失效也照常清理本地状态
      }
      clearAuthToken()
      setActiveTeamId(null)
      this.token = null
      this.user = null
      this.memberships = []
      this.activeTeamId = null
      this.totalCost = 0
      redirectToLogin()
    },
  },
})
