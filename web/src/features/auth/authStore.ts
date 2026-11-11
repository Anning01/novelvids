import { defineStore } from 'pinia'
import { api, clearAuthToken, getActiveTeamId, getAuthToken, redirectToLogin, setActiveTeamId, setAuthToken } from '@/api'
import type { AuthMe, AuthUser, LoginResult, Membership, TeamRole } from '@/types'

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
    deploymentRole: 'studio' as 'studio' | 'platform',
    token: getAuthToken(),
    user: null as AuthUser | null,
    memberships: [] as Membership[],
    activeTeamId: getActiveTeamId(),
    totalCost: 0,
    qilingEnabled: false,
    qilingBound: false,
    ownsTeam: false,
    provider: 'password' as 'password' | 'qiling',
    legalReady: false,
  }),
  getters: {
    isLoggedIn: (state) => state.enabled === true && Boolean(state.user && state.token),
    isSuperAdmin: (state) => state.user?.is_super_admin === true,
    activeMemberships: (state) => state.memberships.filter(item => item.status !== 0 && item.team_status !== 0),
    membership(): Membership | null {
      return this.activeMemberships.find(item => item.team_id === this.activeTeamId)
        ?? (this.isSuperAdmin && this.activeTeamId === null ? null : this.activeMemberships[0] ?? null)
    },
    role(): TeamRole | 'super' | null {
      if (!this.enabled) return null
      if (this.isSuperAdmin && this.activeTeamId === null) return 'super'
      return this.membership?.role ?? (this.isSuperAdmin ? 'super' : null)
    },
    canAccessSettings(): boolean {
      return this.enabled === false || this.canManageTeams
    },
    canAccessBilling(): boolean {
      return this.enabled === false || this.role === 'admin' || this.role === 'creator' || this.role === 'super'
    },
    canManageMembers(): boolean {
      return this.role === 'admin' || this.role === 'super'
    },
    canManageTeams(): boolean {
      return this.role === 'super' || (this.isSuperAdmin && this.role === 'admin')
    },
  },
  actions: {
    async bootstrap(): Promise<void> {
      if (this.ready) return
      try {
        const status = await api.authStatus()
        this.deploymentRole = status.data.deployment_role ?? 'studio'
        this.enabled = status.data.enabled
        this.qilingEnabled = status.data.qiling_enabled === true
        this.provider = status.data.provider ?? (this.qilingEnabled ? 'qiling' : 'password')
        this.legalReady = status.data.legal_ready === true
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
    applyMe(me: AuthMe): void {
      this.user = me.user
      this.memberships = me.memberships
      this.totalCost = Number(me.total_cost ?? 0)
      this.qilingBound = me.qiling_bound === true
      this.ownsTeam = me.owns_team === true
      this.activeTeamId = this._resolveActiveTeam()
    },
    _resolveActiveTeam(): number | null {
      const saved = getActiveTeamId()
      if (saved !== null && this.activeMemberships.some(item => item.team_id === saved)) return saved
      const first = this.isSuperAdmin ? null : this.activeMemberships[0]?.team_id ?? null
      setActiveTeamId(first)
      return first
    },
    setActiveTeam(teamId: number | null): void {
      setActiveTeamId(teamId)
      this.activeTeamId = teamId
    },
    async acceptSession(session: LoginResult): Promise<void> {
      setActiveTeamId(null)
      setAuthToken(session.token)
      this.token = session.token
      this.user = session.user
      const me = await api.me()
      this.applyMe(me.data)
    },
    async login(username: string, password: string): Promise<void> {
      await this.acceptSession((await api.login(username, password)).data)
    },
    async register(data: { username: string; password: string; nickname?: string; invite_token: string }): Promise<void> {
      await this.acceptSession((await api.register(data)).data)
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
      this.qilingBound = false
      this.ownsTeam = false
      redirectToLogin()
    },
  },
})
