import type { RouteLocationNormalized } from 'vue-router'
import type { useAuthStore } from './authStore'
import type { TeamRole } from '@/types'

type AuthStoreLike = ReturnType<typeof useAuthStore>

export interface GuardDecision {
  redirect?: string
}

const ROLE_RANK: Record<TeamRole, number> = { viewer: 0, creator: 1, admin: 2 }

export function hasRoleAccess(role: TeamRole | 'super' | null, required: TeamRole[] | undefined): boolean {
  if (!required || required.length === 0) return true
  if (role === 'super') return true
  if (role === null) return false
  return ROLE_RANK[role] >= Math.max(...required.map(item => ROLE_RANK[item]))
}

/**
 * 路由守卫决策：
 * - 开关未启用 / 尚未就绪：放行（vanilla 体验）
 * - 公开页（/login）：放行
 * - 已登录：按 meta.roles 校验角色，不满足则回首页
 * - 未登录：跳转登录页
 */
export function resolveAuthGuard(to: RouteLocationNormalized, auth: AuthStoreLike): GuardDecision {
  if (auth.enabled !== true) return {}
  if (to.meta.public === true) return {}
  if (!auth.isLoggedIn) return { redirect: '/login' }
  if (to.meta.superOnly === true && auth.role !== 'super') return { redirect: '/' }
  const required = to.meta.roles as TeamRole[] | undefined
  if (!hasRoleAccess(auth.role, required)) return { redirect: '/' }
  return {}
}
