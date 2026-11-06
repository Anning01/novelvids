<script setup lang="ts">
import { tr } from '@/i18n'
import AppSelect from '@/components/AppSelect.vue'

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
const memberLimit = ref<number | null>(null)

const isLimitReached = computed(() => {
  if (memberLimit.value === null || memberLimit.value === undefined) return false
  return totalMembers.value >= memberLimit.value
})

const inviteRole = ref<TeamRole>('creator')
const roleOptions = computed(() => [
  { value: 'creator', label: tr('创作者') },
  { value: 'viewer', label: tr('查看者') },
  { value: 'admin', label: tr('团队管理员') },
])
const inviteLink = ref('')
const creatingInvite = ref(false)

const teamId = computed<number | undefined>(() => {
  if (auth.role === 'super') return selectedTeamId.value ?? undefined
  return auth.membership?.team_id
})
function isSelf(member: MemberItem) {
  return auth.user !== null && member.user_id === auth.user.id
}

function selectTeam(value: string) {
  const id = Number(value)
  if (id === selectedTeamId.value) return
  selectedTeamId.value = id
  page.value = 1
  void loadMembers()
}

function selectMemberRole(member: MemberItem, role: string) {
  if (member.role === role) return
  member.role = role as TeamRole
  void changeRole(member)
}

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
    if (response.data.member_limit !== undefined) {
      memberLimit.value = response.data.member_limit
    } else {
      memberLimit.value = auth.membership?.member_limit ?? null
    }
    // 删除末页最后一条等场景：当前页为空时回退一页
    if (!members.value.length && page.value > 1) {
      page.value -= 1
      await loadMembers()
    }
  } catch (error) {
    notice.error(error instanceof Error ? error.message : tr('加载成员失败'))
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
    notice.success(tr('邀请链接已生成（24 小时内有效）'))
  } catch (error) {
    notice.error(error instanceof Error ? error.message : tr('生成邀请链接失败'))
  } finally {
    creatingInvite.value = false
  }
}

async function copyInvite() {
  if (!inviteLink.value) return
  try {
    await navigator.clipboard.writeText(inviteLink.value)
    notice.success(tr('链接已复制'))
  } catch {
    notice.error(tr('复制失败，请手动复制'))
  }
}

async function changeRole(member: MemberItem) {
  try {
    await api.updateTeamMember(member.user_id, { role: member.role }, teamId.value)
    notice.success(tr('角色已更新'))
  } catch (error) {
    notice.error(error instanceof Error ? error.message : tr('更新角色失败'))
    await loadMembers()
  }
}

async function toggleStatus(member: MemberItem) {
  try {
    await api.updateTeamMember(member.user_id, { status: member.status === 1 ? 0 : 1 }, teamId.value)
    notice.success(member.status === 1 ? tr('成员已禁用') : tr('成员已启用'))
    await loadMembers()
  } catch (error) {
    notice.error(error instanceof Error ? error.message : tr('操作失败'))
  }
}

async function setLimit(member: MemberItem) {
  const raw = window.prompt(
    tr('为「{p0}」设置累计消费限额（元），留空或 0 表示不限：', { p0: member.nickname || member.username }),
    member.cost_limit === null || member.cost_limit === undefined ? '' : String(member.cost_limit),
  )
  if (raw === null) return
  const value = raw.trim() === '' ? null : Number(raw)
  if (value !== null && (Number.isNaN(value) || value < 0)) return
  try {
    await api.setTeamMemberLimit(member.user_id, value === 0 ? null : value, teamId.value)
    notice.success(tr('限额已更新'))
    await loadMembers()
  } catch (error) {
    notice.error(error instanceof Error ? error.message : tr('设置限额失败'))
  }
}

async function removeMember(member: MemberItem) {
  if (!window.confirm(tr('确认将「{p0}」移出团队？', { p0: member.nickname || member.username }))) return
  try {
    await api.removeTeamMember(member.user_id, teamId.value)
    notice.success(tr('成员已移除'))
    await loadMembers()
  } catch (error) {
    notice.error(error instanceof Error ? error.message : tr('移除成员失败'))
  }
}

async function resetPassword(member: MemberItem) {
  const newPassword = window.prompt(tr('为「{p0}」设置新密码（至少 8 位）：', { p0: member.nickname || member.username }))
  if (!newPassword || newPassword.length < 8) return
  try {
    await api.resetTeamMemberPassword(member.user_id, { new_password: newPassword }, teamId.value)
    notice.success(tr('密码已重置'))
  } catch (error) {
    notice.error(error instanceof Error ? error.message : tr('重置密码失败'))
  }
}

async function editTeamLimit() {
  if (!teamId.value) return
  const currentLimitStr = memberLimit.value === null || memberLimit.value === undefined ? '' : String(memberLimit.value)
  const raw = window.prompt(
    tr('设置团队成员上限（留空或 0 表示不限）：'),
    currentLimitStr,
  )
  if (raw === null) return
  const value = raw.trim() === '' ? null : Number(raw)
  if (value !== null && (Number.isNaN(value) || value < 1)) return
  try {
    await api.updateTeam(teamId.value, { member_limit: value === 0 ? null : value })
    notice.success(tr('人员上限已更新'))
    await loadMembers()
    if (auth.role === 'super') await loadTeams()
  } catch (error) {
    notice.error(error instanceof Error ? error.message : tr('设置上限失败'))
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
      <div class="header-title-group">
        <h1>{{ tr('成员管理') }}</h1>
        <span
          v-if="memberLimit !== null && memberLimit !== undefined"
          class="capacity-badge"
          :class="{ 'is-limit': isLimitReached }"
        >
          {{ tr('上限 {p0} 人', { p0: memberLimit }) }}
        </span>
      </div>
      <div v-if="auth.role === 'super'" class="team-picker">
        <span>{{ tr('团队') }}</span>
        <AppSelect
          :model-value="String(selectedTeamId ?? '')"
          :options="teams.map(team => ({ value: String(team.id), label: team.name }))"
          :ariaLabel="tr('团队')"
          :disabled="!teams.length"
          @update:model-value="selectTeam"
        />
        <button v-if="teamId" type="button" class="ghost-button" @click="editTeamLimit">
          {{ tr('修改上限') }}
        </button>
      </div>
    </header>

    <section class="panel">
      <div class="panel-header-row">
        <h2>{{ tr('邀请成员') }}</h2>
        <span class="limit-hint">
          {{ tr('团队人数上限：{p0}', { p0: memberLimit !== null && memberLimit !== undefined ? `${memberLimit} 人` : tr('不限') }) }}
        </span>
      </div>
      <p class="dim">{{ tr('邀请链接 24 小时有效。受邀成员使用器灵登录后确认加入。') }}</p>

      <div v-if="isLimitReached" class="limit-warning-banner">
        <span class="limit-warning-icon">⚠️</span>
        <span class="limit-warning-text">
          {{ tr('当前团队人数已达上限（{p0} 人），新成员将无法加入。如需扩容，请联系平台超级管理员。', { p0: memberLimit }) }}
        </span>
      </div>

      <div class="invite-row">
        <AppSelect
          :model-value="inviteRole"
          :options="roleOptions"
          :ariaLabel="tr('邀请角色')"
          @update:model-value="inviteRole = $event as TeamRole"
        />
        <button
          type="button"
          class="primary-button"
          :disabled="creatingInvite || isLimitReached"
          :title="isLimitReached ? tr('团队人数已达上限，如需扩容请联系平台超级管理员') : ''"
          @click="createInvite"
        >
          {{ creatingInvite ? tr('生成中…') : tr('生成邀请链接') }}
        </button>
        <span v-if="auth.role !== 'super'" class="contact-admin-tip">
          {{ tr('如需扩容人员上限，请联系平台超级管理员') }}
        </span>
      </div>
      <div v-if="inviteLink" class="invite-link-row">
        <input :value="inviteLink" type="text" readonly />
        <button type="button" class="ghost-button" @click="copyInvite">{{ tr('复制') }}</button>
      </div>
    </section>

    <section class="panel">
      <div class="panel-header-row">
        <h2>{{ tr('成员列表（') }}{{ totalMembers }}）</h2>
        <span v-if="memberLimit !== null && memberLimit !== undefined" class="capacity-ratio">
          {{ tr('当前成员：{p0} / {p1} 人', { p0: totalMembers, p1: memberLimit }) }}
        </span>
      </div>
      <p v-if="loading" class="dim">{{ tr('加载中…') }}</p>
      <table v-else class="member-table">
        <thead>
          <tr>
            <th>{{ tr('用户名') }}</th><th>{{ tr('昵称') }}</th><th>{{ tr('角色') }}</th><th>{{ tr('状态') }}</th>
            <th>{{ tr('历史消耗（元）') }}</th><th>{{ tr('消费限额（元）') }}</th><th class="actions">{{ tr('操作') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="member in members" :key="member.user_id" :class="{ 'is-disabled': member.status !== 1 }">
            <td>{{ member.username.startsWith('qiling-') ? (member.nickname || tr('微信用户')) : member.username }}<span v-if="isSelf(member)" class="self-mark">{{ tr('本人') }}</span></td>
            <td>{{ member.nickname || '—' }}</td>
            <td>
              <AppSelect
                :model-value="member.role"
                :options="roleOptions"
                :ariaLabel="tr('角色') + ' · ' + member.username"
                :disabled="isSelf(member)"
                @update:model-value="selectMemberRole(member, $event)"
              />
            </td>
            <td>
              <span class="status-badge" :class="member.status === 1 ? 'is-active' : 'is-stopped'">
                {{ member.status === 1 ? tr('正常') : tr('已禁用') }}
              </span>
            </td>
            <td class="cost">{{ money(member.total_cost) }}</td>
            <td>{{ member.cost_limit === null || member.cost_limit === undefined ? tr('不限') : money(member.cost_limit) }}</td>
            <td class="actions">
              <template v-if="isSelf(member)">
                <span class="dim">{{ tr('不可操作本人') }}</span>
              </template>
              <template v-else>
                <button type="button" class="ghost-button" @click="toggleStatus(member)">{{ member.status === 1 ? tr('禁用') : tr('启用') }}</button>
                <button type="button" class="ghost-button" @click="setLimit(member)">{{ tr('限额') }}</button>
                <button v-if="auth.provider === 'password'" type="button" class="ghost-button" @click="resetPassword(member)">{{ tr('重置密码') }}</button>
                <button type="button" class="danger-button" @click="removeMember(member)">{{ tr('移除') }}</button>
              </template>
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
.members-page { max-width: 1080px; margin: 0 auto; padding: 28px 24px; display: flex; flex-direction: column; gap: 18px; }
.page-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.header-title-group { display: flex; align-items: center; gap: 10px; }
.capacity-badge {
  font-size: 12px; font-weight: 500; padding: 2px 8px; border-radius: 999px;
  background: var(--app-accent-soft, rgba(91, 92, 246, 0.1));
  color: var(--app-accent, #5b5cf6);
}
.capacity-badge.is-limit {
  background: rgba(220, 38, 38, 0.1);
  color: var(--app-danger, #dc2626);
}
.page-header h1 { margin: 0; font-size: 22px; color: var(--app-text, #303442); }
.team-picker { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--app-text-muted, #9398a8); }
.panel { background: var(--app-surface, #fff); border: 1px solid var(--app-border, #e3e5ec); border-radius: 12px; padding: 18px; }
.panel h2 { margin: 0 0 12px; font-size: 15px; color: var(--app-text, #303442); }
.panel-header-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
.panel-header-row h2 { margin: 0; }
.limit-hint, .capacity-ratio { font-size: 13px; color: var(--app-text-muted, #9398a8); }
.limit-warning-banner {
  display: flex; align-items: center; gap: 8px; padding: 10px 14px; margin-bottom: 12px;
  border-radius: 8px; background: var(--app-surface-muted, #f8f9fa);
  border: 1px solid var(--app-border, #e3e5ec);
  color: var(--creation-warning, #9a6a12); font-size: 13px;
}
.contact-admin-tip {
  font-size: 12px; color: var(--app-text-muted, #9398a8); align-self: center; margin-left: 6px;
}
.invite-row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.invite-link-row { display: flex; gap: 8px; margin-top: 10px; }
.invite-link-row input { flex: 1; }
.invite-link-row input {
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
.self-mark { margin-left: 6px; padding: 1px 6px; border-radius: 999px; color: var(--app-accent); background: var(--app-accent-soft); font-size: 11px; font-weight: 600; }
.is-disabled { opacity: 0.55; }
.status-badge { padding: 2px 8px; border-radius: 999px; font-size: 12px; }
.status-badge.is-active { background: var(--app-success-soft, rgba(16, 185, 129, 0.12)); color: var(--app-success, #059669); }
.status-badge.is-stopped { background: var(--app-danger-soft, rgba(220, 38, 38, 0.1)); color: var(--app-danger, #dc2626); }
.dim { color: var(--app-text-muted, #9398a8); font-size: 13px; margin: 0 0 10px; }
</style>
