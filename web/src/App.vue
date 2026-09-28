<script setup lang="ts">
import { tr } from '@/i18n'

import { ElConfigProvider } from 'element-plus'
import { elementLocale } from '@/i18n'
import { BarChart3, Building2, Clapperboard, FolderKanban, Images, RefreshCcw, Settings, Sparkles, UserRound, Users } from 'lucide-vue-next'
import { useRoute } from 'vue-router'
import { computed } from 'vue'
import { notice } from '@/shared/notice'
import AppConfirmDialog from '@/components/AppConfirmDialog.vue'
import AppNotice from '@/components/AppNotice.vue'
import AppThemeToggle from '@/components/AppThemeToggle.vue'
import { useAppThemeController } from '@/shared/appTheme'
import { isWorkflowThemeSurface } from '@/shared/themeScope'
import { useAuthStore } from '@/features/auth/authStore'

const route = useRoute()
const auth = useAuthStore()
const { resolvedTheme } = useAppThemeController()
const isFullscreen = computed(() => route.meta.fullscreen === true)
const hasWorkspaceThemeControl = computed(() => /^\/create\/short-drama\/(agent|manual|storyboard|video)\//.test(route.path))
const isWorkflowSurface = computed(() => isWorkflowThemeSurface({
  name: route.name,
  path: route.path,
  view: route.query.view,
}))
const confirmDialogDark = computed(() => isWorkflowSurface.value || resolvedTheme.value === 'dark')
const creationItems = [
  { path: '/create/short-drama', get label() { return tr('短剧制作') }, icon: Clapperboard, active: () => route.path.startsWith('/create/short-drama') },
  { path: '/create/remake', get label() { return tr('重制工坊') }, icon: RefreshCcw, active: () => route.path.startsWith('/create/remake') },
]
// 按角色渲染「我的」导航：成本（管理员/创作者/超管）、设置（管理员/超管）；
// AUTH_ENABLED=false 时全部可见（vanilla 体验）
const personalItems = computed(() => {
  const items = [
    { path: '/projects', get label() { return tr('项目') }, icon: FolderKanban, active: () => route.path === '/projects' || route.path.startsWith('/novel') },
    { path: '/assets', get label() { return tr('资产') }, icon: Images, active: () => route.path.startsWith('/assets') },
  ]
  if (auth.canAccessBilling) items.push({ path: '/billing', get label() { return tr('成本') }, icon: BarChart3, active: () => route.path.startsWith('/billing') })
  if (auth.canAccessSettings) items.push({ path: '/settings', get label() { return tr('设置') }, icon: Settings, active: () => route.path.startsWith('/settings') })
  return items
})
// 组织治理导航：仅开启登录且具备管理权限时显示（团队管理员/超管）
const adminItems = computed(() => {
  const items = []
  if (auth.enabled === true && auth.canManageMembers) items.push({ path: '/members', get label() { return tr('成员管理') }, icon: Users, active: () => route.path.startsWith('/members') })
  if (auth.enabled === true && auth.canManageTeams) {
    items.push({ path: '/teams', get label() { return tr('团队管理') }, icon: Building2, active: () => route.path.startsWith('/teams') })
    items.push({ path: '/users', get label() { return tr('用户管理') }, icon: UserRound, active: () => route.path.startsWith('/users') })
  }
  return items
})
const userLabel = computed(() => auth.user?.nickname || auth.user?.username || '')
const avatarText = computed(() => userLabel.value.slice(0, 1).toUpperCase())
const money = (value: number | string | null | undefined) => {
  const parsed = Number(value ?? 0)
  return Number.isFinite(parsed) ? parsed.toFixed(2) : '0.00'
}
// 左下角消费信息：管理员显示团队余额；成员显示自己的限额，不限则显示团队余额；超管不显示
const walletLabel = computed(() => {
  if (auth.enabled !== true || !auth.isLoggedIn || auth.role === 'super') return ''
  const membership = auth.membership
  if (!membership) return ''
  if (auth.role === 'admin') return tr('余额 ¥{p0}', { p0: money(membership.team_balance) })
  if (membership.cost_limit !== null && membership.cost_limit !== undefined) return tr('限额 ¥{p0}', { p0: money(membership.cost_limit) })
  return tr('余额 ¥{p0}', { p0: money(membership.team_balance) })
})
function handleTeamSwitch(event: Event) {
  const value = Number((event.target as HTMLSelectElement).value)
  if (!value || value === auth.activeTeamId) return
  auth.setActiveTeam(value)
  // 切换团队后重载当前页面，全部数据按新团队作用域重新拉取
  window.location.reload()
}
</script>
<template>
  <ElConfigProvider :locale="elementLocale">
  <div class="app-shell" :class="{ 'is-workflow-surface': isWorkflowSurface }">
    <aside v-if="!isFullscreen" class="app-sidebar">
      <RouterLink to="/" class="app-brand" :aria-label="tr('猫影首页')">
        <img src="/logo.png" alt="" />
        <span>
          <strong>{{ tr('猫影') }}</strong>
          <small>NOVEL STUDIO</small>
        </span>
      </RouterLink>
      <label
        v-if="auth.enabled === true && auth.isLoggedIn && auth.memberships.length"
        class="app-team-selector"
      >
        <select :value="auth.activeTeamId ?? ''" :aria-label="tr('切换团队')" @change="handleTeamSwitch">
          <option v-for="item in auth.memberships" :key="item.team_id" :value="item.team_id">
            {{ item.team_name }}
          </option>
        </select>
      </label>
      <div
        v-else-if="auth.enabled === true && auth.isLoggedIn && auth.isSuperAdmin"
        class="app-team-selector app-team-selector--super"
      > {{ tr('平台管理员 · 全部团队') }} </div>
      <nav :aria-label="tr('主导航')">
        <RouterLink to="/" :aria-label="tr('首页')" class="app-nav-item app-home-item" :class="{ 'is-active': route.path === '/' }">
          <Sparkles :size="18" />
          <span>{{ tr('首页') }}</span>
        </RouterLink>

        <section class="app-nav-group" aria-labelledby="creation-nav-title">
          <h2 id="creation-nav-title">{{ tr('创作') }}</h2>
          <RouterLink v-for="item in creationItems" :key="item.path" :to="item.path" :aria-label="item.label" class="app-nav-item" :class="{ 'is-active': item.active() }">
            <component :is="item.icon" :size="18" />
            <span>{{ item.label }}</span>
          </RouterLink>
        </section>

        <section class="app-nav-group" aria-labelledby="personal-nav-title">
          <h2 id="personal-nav-title">{{ tr('我的') }}</h2>
          <RouterLink v-for="item in personalItems" :key="item.path" :to="item.path" :aria-label="item.label" class="app-nav-item" :class="{ 'is-active': item.active() }">
            <component :is="item.icon" :size="18" />
            <span>{{ item.label }}</span>
          </RouterLink>
        </section>

        <section v-if="adminItems.length" class="app-nav-group" aria-labelledby="admin-nav-title">
          <h2 id="admin-nav-title">{{ tr('管理') }}</h2>
          <RouterLink v-for="item in adminItems" :key="item.path" :to="item.path" :aria-label="item.label" class="app-nav-item" :class="{ 'is-active': item.active() }">
            <component :is="item.icon" :size="18" />
            <span>{{ item.label }}</span>
          </RouterLink>
        </section>
      </nav>
      <RouterLink
        v-if="auth.enabled === true && auth.isLoggedIn"
        to="/profile"
        class="app-user-block"
        :class="{ 'is-active': route.path === '/profile' }"
        :title="tr('用户中心：{p0}', { p0: userLabel })"
      >
        <span class="app-user-avatar">{{ avatarText }}</span>
        <span class="app-user-copy">
          <span class="app-user-name">{{ userLabel }}</span>
          <small v-if="walletLabel" class="app-user-wallet">{{ walletLabel }}</small>
        </span>
      </RouterLink>
      <AppThemeToggle v-if="!isWorkflowSurface" placement="sidebar" />
    </aside>
    <section class="app-content" :class="{ 'is-fullscreen': isFullscreen }"><RouterView /></section>
    <AppThemeToggle v-if="isFullscreen && !isWorkflowSurface && !hasWorkspaceThemeControl" />
    <AppConfirmDialog :dark="confirmDialogDark" />
    <TransitionGroup name="notice" tag="div" class="notice-stack" aria-live="polite"><AppNotice v-for="item in notice.state.notices" :key="item.id" :item="item" /></TransitionGroup>
  </div>
  </ElConfigProvider>
</template>

<style scoped>
.app-team-selector {
  display: block;
  margin: 0 10px 10px;
}
.app-team-selector select {
  width: 100%;
  height: 34px;
  padding: 0 10px;
  border: 1px solid var(--app-border, #e3e5ec);
  border-radius: 9px;
  background: var(--app-surface-muted, #f2f3f7);
  color: var(--app-text, #303442);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.app-team-selector select:hover { border-color: var(--app-border-strong, #d3d6e0); background: var(--app-surface-hover, #f0f1f6); }
.app-team-selector--super {
  padding: 0 10px;
  font-size: 12px;
  font-weight: 600;
  color: var(--app-text-muted, #9398a8);
}
.app-user-block {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  margin: 0 10px 10px;
  border: 1px solid var(--app-border, #e3e5ec);
  border-radius: 10px;
  background: var(--app-surface, #fff);
  color: var(--app-text, #303442);
  text-decoration: none;
  transition: border-color .15s ease, background-color .15s ease;
}
.app-user-block:hover { border-color: var(--app-border-strong, #d3d6e0); background: var(--app-surface-hover, #f0f1f6); }
.app-user-block.is-active { color: var(--app-accent, #5b5cf6); background: var(--app-accent-soft, #eeefff); }
.app-user-avatar {
  display: flex;
  width: 28px;
  height: 28px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  border-radius: 9px;
  color: #fff;
  background: var(--app-accent, #5b5cf6);
  font-size: 13px;
  font-weight: 700;
}
.app-user-copy { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 2px; }
.app-user-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 600;
}
.app-user-wallet { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; color: var(--app-text-muted, #9398a8); font-variant-numeric: tabular-nums; }
</style>
