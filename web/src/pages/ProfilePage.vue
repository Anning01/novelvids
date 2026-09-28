<script setup lang="ts">
import { tr } from '@/i18n'

import { computed, onMounted, ref } from 'vue'
import { api } from '@/api'
import { notice } from '@/shared/notice'
import { useAuthStore } from '@/features/auth/authStore'

const auth = useAuthStore()

const passwordForm = ref({ oldPassword: '', newPassword: '', confirmPassword: '' })
const changing = ref(false)

const displayName = computed(() => auth.user?.nickname || auth.user?.username || '')
const avatarText = computed(() => displayName.value.slice(0, 1).toUpperCase())
const totalCost = computed(() => Number(auth.totalCost ?? 0).toFixed(2))
const registeredAt = computed(() => auth.user?.created_at || '—')
const roleLabel = (role: string) => ({ get admin() { return tr('团队管理员') }, get creator() { return tr('创作者') }, get viewer() { return tr('查看者') } }[role] || role)
const money = (value: number | string | null | undefined) => {
  const parsed = Number(value ?? 0)
  return Number.isFinite(parsed) ? parsed.toFixed(2) : '0.00'
}

async function changePassword() {
  const { oldPassword, newPassword, confirmPassword } = passwordForm.value
  if (!oldPassword || newPassword.length < 8) return
  if (newPassword !== confirmPassword) {
    notice.error(tr('两次输入的新密码不一致'))
    return
  }
  changing.value = true
  try {
    await api.changePassword(oldPassword, newPassword)
    notice.success(tr('密码已修改'))
    passwordForm.value = { oldPassword: '', newPassword: '', confirmPassword: '' }
  } catch (error) {
    notice.error(error instanceof Error ? error.message : tr('修改密码失败'))
  } finally {
    changing.value = false
  }
}

async function logout() {
  await auth.logout()
}

onMounted(async () => {
  // 确保展示最新的累计消耗与注册信息
  try {
    await auth.refreshMe()
  } catch {
    // 会话失效时由全局 401 处理跳转
  }
})
</script>

<template>
  <main class="profile-page">
    <header class="profile-header">
      <div class="profile-avatar">{{ avatarText }}</div>
      <div class="profile-identity">
        <h1>{{ displayName }}</h1>
        <p>@{{ auth.user?.username }}<span v-if="auth.isSuperAdmin" class="profile-role">{{ tr('超级管理员') }}</span></p>
      </div>
    </header>

    <section class="profile-grid">
      <div class="profile-card">
        <h2>{{ tr('我的信息') }}</h2>
        <dl class="profile-stats">
          <div>
            <dt>{{ tr('历史创作花费') }}</dt>
            <dd class="cost">¥ {{ totalCost }}</dd>
          </div>
          <div>
            <dt>{{ tr('注册时间') }}</dt>
            <dd>{{ registeredAt }}</dd>
          </div>
        </dl>
      </div>

      <div class="profile-card">
        <h2>{{ tr('加入的团队') }}</h2>
        <p v-if="!auth.memberships.length" class="dim">{{ tr('尚未加入任何团队') }}</p>
        <ul v-else class="team-list">
          <li v-for="item in auth.memberships" :key="item.team_id">
            <div class="team-info">
              <strong>{{ item.team_name }}</strong>
              <span>{{ roleLabel(item.role) }}<template v-if="item.status === 0"> {{ tr('· 已禁用') }}</template></span>
            </div>
            <div class="team-meta">
              <span>{{ tr('累计 ¥') }}{{ money(item.total_cost) }}</span>
              <span v-if="item.joined_at">{{ tr('加入于') }} {{ item.joined_at }}</span>
            </div>
          </li>
        </ul>
      </div>

      <div class="profile-card">
        <h2>{{ tr('修改密码') }}</h2>
        <form class="password-form" @submit.prevent="changePassword">
          <label>
            <span>{{ tr('当前密码') }}</span>
            <input v-model="passwordForm.oldPassword" type="password" autocomplete="current-password" required />
          </label>
          <label>
            <span>{{ tr('新密码（至少 8 位）') }}</span>
            <input v-model="passwordForm.newPassword" type="password" autocomplete="new-password" required minlength="8" />
          </label>
          <label>
            <span>{{ tr('确认新密码') }}</span>
            <input v-model="passwordForm.confirmPassword" type="password" autocomplete="new-password" required minlength="8" />
          </label>
          <button type="submit" class="primary-button" :disabled="changing">{{ changing ? tr('提交中…') : tr('修改密码') }}</button>
        </form>
      </div>
    </section>

    <button type="button" class="logout-button" @click="logout">{{ tr('退出登录') }}</button>
  </main>
</template>

<style scoped>
.profile-page { max-width: 760px; margin: 0 auto; padding: 28px 24px 60px; display: flex; flex-direction: column; gap: 18px; min-height: 100%; color: var(--app-text, #303442); background: var(--app-surface, #fff); }
.profile-header { display: flex; align-items: center; gap: 14px; }
.profile-avatar { display: flex; width: 56px; height: 56px; align-items: center; justify-content: center; border-radius: 16px; color: #fff; background: var(--app-accent, #5b5cf6); font-size: 22px; font-weight: 700; }
.profile-identity h1 { margin: 0; font-size: 20px; color: var(--app-text, #303442); }
.profile-identity p { margin: 4px 0 0; font-size: 13px; color: var(--app-text-muted, #9398a8); }
.profile-role { margin-left: 8px; padding: 2px 8px; border-radius: 999px; color: var(--app-accent, #5b5cf6); background: var(--app-accent-soft, #eeefff); font-size: 11px; }
.profile-grid { display: grid; gap: 16px; }
.profile-card { padding: 18px; border: 1px solid var(--app-border, #e3e5ec); border-radius: 12px; background: var(--app-surface, #fff); box-shadow: var(--app-shadow, 0 12px 34px rgb(37 41 57 / 7%)); }
.profile-card h2 { margin: 0 0 12px; font-size: 15px; color: var(--app-text, #303442); }
.profile-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 0; }
.profile-stats dt { font-size: 12px; color: var(--app-text-muted, #9398a8); }
.profile-stats dd { margin: 4px 0 0; font-size: 15px; color: var(--app-text, #303442); }
.profile-stats .cost { color: var(--app-accent, #5b5cf6); font-weight: 700; font-variant-numeric: tabular-nums; }
.team-list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 10px; }
.team-list li { display: flex; justify-content: space-between; gap: 12px; padding: 10px 12px; border: 1px solid var(--app-border, #e3e5ec); border-radius: 10px; background: var(--app-surface-muted, #f2f3f7); }
.team-info { display: flex; flex-direction: column; gap: 2px; }
.team-info strong { font-size: 14px; color: var(--app-text, #303442); }
.team-info span { font-size: 12px; color: var(--app-text-muted, #9398a8); }
.team-meta { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; font-size: 12px; color: var(--app-text-secondary, #656b7b); }
.password-form { display: flex; flex-direction: column; gap: 10px; }
.password-form label { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: var(--app-text-muted, #9398a8); }
.password-form input { height: 36px; padding: 0 10px; border: 1px solid var(--app-border, #e3e5ec); border-radius: 8px; background: var(--app-surface-muted, #f2f3f7); color: var(--app-text, #303442); font-size: 13px; }
.primary-button { height: 38px; border: none; border-radius: 9px; background: var(--app-accent, #5b5cf6); color: #fff; font-size: 14px; font-weight: 600; cursor: pointer; }
.primary-button:disabled { opacity: 0.6; }
.logout-button { width: 100%; height: 40px; border: 1px solid var(--app-border, #e3e5ec); border-radius: 10px; color: #dc2626; background: var(--app-surface, #fff); font-size: 14px; font-weight: 600; cursor: pointer; }
.dim { margin: 0; color: var(--app-text-muted, #9398a8); font-size: 13px; }
</style>
