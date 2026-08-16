<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '@/api'
import AppPagination from '@/components/AppPagination.vue'
import { notice } from '@/shared/notice'
import type { UserItem, UserStats } from '@/types'

const stats = ref<UserStats>({ user_count: 0, user_total_cost: 0, team_count: 0, team_balance_total: 0 })
const users = ref<UserItem[]>([])
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const totalUsers = ref(0)

const showCreateDialog = ref(false)
const createForm = ref({ username: '', nickname: '', password: '' })
const creating = ref(false)

const money = (value: number | string | null | undefined) => {
  const parsed = Number(value ?? 0)
  return Number.isFinite(parsed) ? parsed.toFixed(2) : '0.00'
}

async function load() {
  loading.value = true
  try {
    const [statsResponse, usersResponse] = await Promise.all([
      api.userStats(),
      api.users(page.value, pageSize.value),
    ])
    stats.value = statsResponse.data
    users.value = usersResponse.data.items
    totalUsers.value = usersResponse.data.pagination.total
    if (!users.value.length && page.value > 1) {
      page.value -= 1
      await load()
    }
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '加载用户失败')
  } finally {
    loading.value = false
  }
}

async function createUser() {
  if (!createForm.value.username.trim() || createForm.value.password.length < 8) return
  creating.value = true
  try {
    await api.createUser({
      username: createForm.value.username.trim(),
      nickname: createForm.value.nickname,
      password: createForm.value.password,
    })
    notice.success('用户已创建')
    showCreateDialog.value = false
    createForm.value = { username: '', nickname: '', password: '' }
    await load()
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '创建用户失败')
  } finally {
    creating.value = false
  }
}

async function toggleStatus(user: UserItem) {
  try {
    await api.updateUser(user.id, { status: user.status === 1 ? 0 : 1 })
    notice.success(user.status === 1 ? '已禁用登录' : '已恢复登录')
    await load()
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '操作失败')
  }
}

async function removeUser(user: UserItem) {
  if (!window.confirm(`确认删除用户「${user.nickname || user.username}」？其团队关系与会话将一并删除。`)) return
  try {
    await api.deleteUser(user.id)
    notice.success('用户已删除')
    await load()
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '删除失败')
  }
}

function changePage(next: number) {
  page.value = next
  void load()
}

function changePageSize(size: number) {
  pageSize.value = size
  page.value = 1
  void load()
}

onMounted(load)
</script>

<template>
  <main class="users-page">
    <header class="page-header">
      <h1>用户管理</h1>
      <button type="button" class="primary-button" @click="showCreateDialog = true">创建用户</button>
    </header>

    <section class="stats-row">
      <div class="stat-card">
        <span class="stat-label">用户总数</span>
        <strong class="stat-value">{{ stats.user_count }}</strong>
      </div>
      <div class="stat-card">
        <span class="stat-label">用户总消耗金额</span>
        <strong class="stat-value is-cost">¥ {{ money(stats.user_total_cost) }}</strong>
      </div>
      <div class="stat-card">
        <span class="stat-label">团队总数</span>
        <strong class="stat-value">{{ stats.team_count }}</strong>
      </div>
      <div class="stat-card">
        <span class="stat-label">团队未消耗总金额</span>
        <strong class="stat-value is-balance">¥ {{ money(stats.team_balance_total) }}</strong>
      </div>
    </section>

    <section class="panel">
      <p v-if="loading" class="dim">加载中…</p>
      <table v-else class="user-table">
        <thead>
          <tr>
            <th>用户名</th><th>昵称</th><th>类型</th><th>登录状态</th>
            <th>注册时间</th><th>累计消耗（元）</th><th>团队数</th><th class="actions">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="user in users" :key="user.id" :class="{ 'is-disabled': user.status !== 1 }">
            <td>{{ user.username }}</td>
            <td>{{ user.nickname || '—' }}</td>
            <td>
              <span v-if="user.is_super_admin" class="kind-badge is-super">超管</span>
              <span v-else class="kind-badge">普通</span>
            </td>
            <td>
              <span class="status-badge" :class="user.status === 1 ? 'is-active' : 'is-stopped'">
                {{ user.status === 1 ? '正常' : '已禁用' }}
              </span>
            </td>
            <td>{{ user.created_at || '—' }}</td>
            <td class="cost">{{ money(user.total_cost) }}</td>
            <td>{{ user.team_count ?? 0 }}</td>
            <td class="actions">
              <template v-if="!user.is_super_admin">
                <button type="button" class="ghost-button" @click="toggleStatus(user)">
                  {{ user.status === 1 ? '禁用登录' : '恢复登录' }}
                </button>
                <button type="button" class="danger-button" @click="removeUser(user)">删除</button>
              </template>
              <span v-else class="dim">—</span>
            </td>
          </tr>
        </tbody>
      </table>
      <AppPagination
        :page="page"
        :page-size="pageSize"
        :total="totalUsers"
        @page-change="changePage"
        @size-change="changePageSize"
      />
    </section>

    <div v-if="showCreateDialog" class="dialog-mask" @click.self="showCreateDialog = false">
      <form class="dialog-card" @submit.prevent="createUser">
        <h2>创建用户</h2>
        <p class="dim">创建后该用户暂无团队，可经邀请链接加入团队。</p>
        <label>
          <span>用户名</span>
          <input v-model="createForm.username" type="text" autocomplete="off" required />
        </label>
        <label>
          <span>昵称（可选）</span>
          <input v-model="createForm.nickname" type="text" />
        </label>
        <label>
          <span>初始密码（至少 8 位）</span>
          <input v-model="createForm.password" type="password" autocomplete="new-password" required minlength="8" />
        </label>
        <div class="dialog-actions">
          <button type="button" class="ghost-button" @click="showCreateDialog = false">取消</button>
          <button type="submit" class="primary-button" :disabled="creating">{{ creating ? '创建中…' : '创建' }}</button>
        </div>
      </form>
    </div>
  </main>
</template>

<style scoped>
.users-page { max-width: 1080px; margin: 0 auto; padding: 28px 24px; display: flex; flex-direction: column; gap: 18px; color: var(--app-text, #303442); background: var(--app-canvas, #f8f9fc); min-height: 100%; }
.page-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.page-header h1 { margin: 0; font-size: 22px; }
.stats-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.stat-card { display: flex; flex-direction: column; gap: 6px; padding: 16px; border: 1px solid var(--app-border, #e3e5ec); border-radius: 12px; background: var(--app-surface, #fff); box-shadow: var(--app-shadow, 0 12px 34px rgb(37 41 57 / 7%)); }
.stat-label { font-size: 12px; color: var(--app-text-muted, #9398a8); }
.stat-value { font-size: 22px; color: var(--app-text, #303442); font-variant-numeric: tabular-nums; }
.stat-value.is-cost { color: var(--app-accent, #5b5cf6); }
.stat-value.is-balance { color: #059669; }
.panel { padding: 18px; border: 1px solid var(--app-border, #e3e5ec); border-radius: 12px; background: var(--app-surface, #fff); }
.user-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.user-table th, .user-table td { text-align: left; padding: 9px 10px; border-bottom: 1px solid var(--app-border, #e3e5ec); }
.user-table .actions { text-align: right; white-space: nowrap; }
.user-table .cost { font-variant-numeric: tabular-nums; }
.is-disabled { opacity: 0.55; }
.kind-badge { padding: 2px 8px; border-radius: 999px; font-size: 12px; color: var(--app-text-secondary, #656b7b); background: var(--app-surface-muted, #f2f3f7); }
.kind-badge.is-super { color: var(--app-accent, #5b5cf6); background: var(--app-accent-soft, #eeefff); }
.status-badge { padding: 2px 8px; border-radius: 999px; font-size: 12px; }
.status-badge.is-active { color: #059669; background: rgb(16 185 129 / 12%); }
.status-badge.is-stopped { color: #dc2626; background: rgb(220 38 38 / 10%); }
.ghost-button, .danger-button { height: 28px; padding: 0 10px; border-radius: 8px; font-size: 12px; cursor: pointer; border: 1px solid var(--app-border, #e3e5ec); background: transparent; color: var(--app-text-secondary, #656b7b); margin-left: 6px; }
.danger-button { color: #dc2626; }
.primary-button { height: 36px; padding: 0 16px; border: none; border-radius: 8px; background: var(--app-accent, #5b5cf6); color: #fff; font-weight: 600; cursor: pointer; }
.primary-button:disabled { opacity: 0.6; }
.dim { margin: 0 0 10px; color: var(--app-text-muted, #9398a8); font-size: 13px; }
.dialog-mask { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); display: flex; align-items: center; justify-content: center; z-index: 100; }
.dialog-card { width: 100%; max-width: 380px; padding: 24px; border-radius: 14px; background: var(--app-surface, #fff); display: flex; flex-direction: column; gap: 12px; }
.dialog-card h2 { margin: 0; font-size: 17px; color: var(--app-text, #303442); }
.dialog-card label { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: var(--app-text-muted, #9398a8); }
.dialog-card input { height: 36px; padding: 0 10px; border: 1px solid var(--app-border, #e3e5ec); border-radius: 8px; background: var(--app-surface-muted, #f2f3f7); color: var(--app-text, #303442); font-size: 13px; }
.dialog-actions { display: flex; justify-content: flex-end; gap: 8px; }
.dialog-card .dialog-actions :is(.ghost-button,.primary-button) { height: 36px; padding: 0 16px; font-size: 13px; margin-left: 0; }
</style>
