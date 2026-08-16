<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/api'
import AppPagination from '@/components/AppPagination.vue'
import { notice } from '@/shared/notice'
import { useAuthStore } from '@/features/auth/authStore'
import type { MemberItem, TeamItem, TeamRole } from '@/types'

const auth = useAuthStore()
const route = useRoute()

const teams = ref<TeamItem[]>([])
const selectedTeamId = ref<number | null>(null)
const members = ref<MemberItem[]>([])
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const totalMembers = ref(0)

const inviteRole = ref<TeamRole>('creator')
const inviteLink = ref('')
const creatingInvite = ref(false)

const teamId = computed<number | undefined>(() => {
  if (auth.role === 'super') return selectedTeamId.value ?? undefined
  return auth.membership?.team_id
})
const money = (value: number | string | null | undefined) => {
  const parsed = Number(value ?? 0)
  return Number.isFinite(parsed) ? parsed.toFixed(2) : '0.00'
}

async function loadTeams() {
  if (auth.role !== 'super') return
  const response = await api.teams()
  teams.value = response.data.items
  if (!selectedTeamId.value && teams.value.length) selectedTeamId.value = Number(route.query.team_id) || teams.value[0].id
}

async function loadMembers() {
  if (!teamId.value) return
  loading.value = true
  try {
    const response = await api.teamMembers(page.value, pageSize.value, teamId.value)
    members.value = response.data.items
    totalMembers.value = response.data.pagination.total
    // 删除末页最后一条等场景：当前页为空时回退一页
    if (!members.value.length && page.value > 1) {
      page.value -= 1
      await loadMembers()
    }
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '加载成员失败')
  } finally {
    loading.value = false
  }
}

function changePage(next: number) {
  page.value = next
  void loadMembers()
}

function changePageSize(size: number) {
  pageSize.value = size
  page.value = 1
  void loadMembers()
}

async function createInvite() {
  if (!teamId.value) return
  creatingInvite.value = true
  try {
    const response = await api.createTeamInvite(inviteRole.value, teamId.value)
    inviteLink.value = `${window.location.origin}/#/invite/${response.data.token}`
    notice.success('邀请链接已生成（24 小时内有效）')
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '生成邀请链接失败')
  } finally {
    creatingInvite.value = false
  }
}

async function copyInvite() {
  if (!inviteLink.value) return
  try {
    await navigator.clipboard.writeText(inviteLink.value)
    notice.success('链接已复制')
  } catch {
    notice.error('复制失败，请手动复制')
  }
}

async function changeRole(member: MemberItem) {
  try {
    await api.updateTeamMember(member.user_id, { role: member.role }, teamId.value)
    notice.success('角色已更新')
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '更新角色失败')
    await loadMembers()
  }
}

async function toggleStatus(member: MemberItem) {
  try {
    await api.updateTeamMember(member.user_id, { status: member.status === 1 ? 0 : 1 }, teamId.value)
    notice.success(member.status === 1 ? '成员已禁用' : '成员已启用')
    await loadMembers()
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '操作失败')
  }
}

async function setLimit(member: MemberItem) {
  const raw = window.prompt(
    `为「${member.nickname || member.username}」设置累计消费限额（元），留空或 0 表示不限：`,
    member.cost_limit === null || member.cost_limit === undefined ? '' : String(member.cost_limit),
  )
  if (raw === null) return
  const value = raw.trim() === '' ? null : Number(raw)
  if (value !== null && (Number.isNaN(value) || value < 0)) return
  try {
    await api.setTeamMemberLimit(member.user_id, value === 0 ? null : value, teamId.value)
    notice.success('限额已更新')
    await loadMembers()
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '设置限额失败')
  }
}

async function removeMember(member: MemberItem) {
  if (!window.confirm(`确认将「${member.nickname || member.username}」移出团队？`)) return
  try {
    await api.removeTeamMember(member.user_id, teamId.value)
    notice.success('成员已移除')
    await loadMembers()
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '移除成员失败')
  }
}

async function resetPassword(member: MemberItem) {
  const newPassword = window.prompt(`为「${member.nickname || member.username}」设置新密码（至少 8 位）：`)
  if (!newPassword || newPassword.length < 8) return
  try {
    await api.resetTeamMemberPassword(member.user_id, { new_password: newPassword }, teamId.value)
    notice.success('密码已重置')
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '重置密码失败')
  }
}

onMounted(async () => {
  await loadTeams()
  await loadMembers()
})
</script>

<template>
  <main class="members-page">
    <header class="page-header">
      <h1>成员管理</h1>
      <label v-if="auth.role === 'super'" class="team-picker">
        <span>团队</span>
        <select v-model="selectedTeamId" @change="page = 1; loadMembers()">
          <option v-for="team in teams" :key="team.id" :value="team.id">{{ team.name }}</option>
        </select>
      </label>
    </header>

    <section class="panel">
      <h2>邀请成员</h2>
      <p class="dim">成员加入团队的唯一方式是通过邀请链接（24 小时有效）。新用户经链接注册加入，老用户登录后经链接加入。</p>
      <div class="invite-row">
        <select v-model="inviteRole">
          <option value="creator">创作者</option>
          <option value="viewer">查看者</option>
          <option value="admin">团队管理员</option>
        </select>
        <button type="button" class="primary-button" :disabled="creatingInvite" @click="createInvite">
          {{ creatingInvite ? '生成中…' : '生成邀请链接' }}
        </button>
      </div>
      <div v-if="inviteLink" class="invite-link-row">
        <input :value="inviteLink" type="text" readonly />
        <button type="button" class="ghost-button" @click="copyInvite">复制</button>
      </div>
    </section>

    <section class="panel">
      <h2>成员列表（{{ totalMembers }}）</h2>
      <p v-if="loading" class="dim">加载中…</p>
      <table v-else class="member-table">
        <thead>
          <tr>
            <th>用户名</th><th>昵称</th><th>角色</th><th>状态</th>
            <th>历史消耗（元）</th><th>消费限额（元）</th><th class="actions">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="member in members" :key="member.user_id" :class="{ 'is-disabled': member.status !== 1 }">
            <td>{{ member.username }}</td>
            <td>{{ member.nickname || '—' }}</td>
            <td>
              <select :value="member.role" @change="member.role = ($event.target as HTMLSelectElement).value as TeamRole; changeRole(member)">
                <option value="admin">团队管理员</option>
                <option value="creator">创作者</option>
                <option value="viewer">查看者</option>
              </select>
            </td>
            <td>
              <span class="status-badge" :class="member.status === 1 ? 'is-active' : 'is-stopped'">
                {{ member.status === 1 ? '正常' : '已禁用' }}
              </span>
            </td>
            <td class="cost">{{ money(member.total_cost) }}</td>
            <td>{{ member.cost_limit === null || member.cost_limit === undefined ? '不限' : money(member.cost_limit) }}</td>
            <td class="actions">
              <button type="button" class="ghost-button" @click="toggleStatus(member)">{{ member.status === 1 ? '禁用' : '启用' }}</button>
              <button type="button" class="ghost-button" @click="setLimit(member)">限额</button>
              <button type="button" class="ghost-button" @click="resetPassword(member)">重置密码</button>
              <button type="button" class="danger-button" @click="removeMember(member)">移除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <AppPagination
        :page="page"
        :page-size="pageSize"
        :total="totalMembers"
        @page-change="changePage"
        @size-change="changePageSize"
      />
    </section>
  </main>
</template>

<style scoped>
.members-page { max-width: 980px; margin: 0 auto; padding: 28px 24px; display: flex; flex-direction: column; gap: 18px; }
.page-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.page-header h1 { margin: 0; font-size: 22px; color: var(--app-text, #303442); }
.team-picker { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--app-text-muted, #9398a8); }
.panel { background: var(--app-surface, #fff); border: 1px solid var(--app-border, #e3e5ec); border-radius: 12px; padding: 18px; }
.panel h2 { margin: 0 0 12px; font-size: 15px; color: var(--app-text, #303442); }
.invite-row { display: flex; gap: 8px; }
.invite-link-row { display: flex; gap: 8px; margin-top: 10px; }
.invite-link-row input { flex: 1; }
.invite-row select, .invite-link-row input, .team-picker select, .member-table select {
  height: 36px; padding: 0 10px; border: 1px solid var(--app-border, #e3e5ec); border-radius: 8px;
  background: var(--app-surface-muted, #f2f3f7); color: var(--app-text, #303442); font-size: 13px;
}
.invite-link-row input { font-size: 12px; color: var(--app-text-muted, #9398a8); }
.primary-button { height: 36px; padding: 0 16px; border: none; border-radius: 8px; background: var(--app-accent, #5b5cf6); color: #fff; font-weight: 600; cursor: pointer; }
.primary-button:disabled { opacity: 0.6; }
.ghost-button, .danger-button { height: 28px; padding: 0 10px; border-radius: 8px; font-size: 12px; cursor: pointer; border: 1px solid var(--app-border, #e3e5ec); background: transparent; color: var(--app-text-muted, #9398a8); margin-left: 6px; }
.danger-button { color: var(--app-danger, #dc2626); }
.member-table { width: 100%; border-collapse: collapse; font-size: 13px; color: var(--app-text, #303442); }
.member-table th, .member-table td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--app-border, #e3e5ec); }
.member-table .actions { text-align: right; white-space: nowrap; }
.member-table .cost { font-variant-numeric: tabular-nums; }
.is-disabled { opacity: 0.55; }
.status-badge { padding: 2px 8px; border-radius: 999px; font-size: 12px; }
.status-badge.is-active { background: var(--app-success-soft, rgba(16, 185, 129, 0.12)); color: var(--app-success, #059669); }
.status-badge.is-stopped { background: var(--app-danger-soft, rgba(220, 38, 38, 0.1)); color: var(--app-danger, #dc2626); }
.dim { color: var(--app-text-muted, #9398a8); font-size: 13px; margin: 0 0 10px; }
</style>
