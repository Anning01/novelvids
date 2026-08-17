<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api'
import AppPagination from '@/components/AppPagination.vue'
import AppSelect from '@/components/AppSelect.vue'
import { notice } from '@/shared/notice'
import type { TeamItem, UserItem } from '@/types'

const teams = ref<TeamItem[]>([])
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const totalTeams = ref(0)

const showCreateDialog = ref(false)
const candidates = ref<UserItem[]>([])
const createForm = ref({ name: '', memberLimit: '', ownerUserId: null as number | null })
const creating = ref(false)

const statusLabel = (status: number) => (status === 1 ? '正常' : '已停用')

const ownerOptions = computed(() => candidates.value.map(user => ({
  value: String(user.id),
  label: `${user.nickname || user.username}（${user.username}${user.is_super_admin ? '，超管' : ''}）`,
})))

function selectOwner(value: string) {
  createForm.value.ownerUserId = Number(value)
}

async function loadTeams() {
  loading.value = true
  try {
    const response = await api.teams(page.value, pageSize.value)
    teams.value = response.data.items
    totalTeams.value = response.data.pagination.total
    if (!teams.value.length && page.value > 1) {
      page.value -= 1
      await loadTeams()
    }
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '加载团队失败')
  } finally {
    loading.value = false
  }
}

function changePage(next: number) {
  page.value = next
  void loadTeams()
}

function changePageSize(size: number) {
  pageSize.value = size
  page.value = 1
  void loadTeams()
}

async function openCreateDialog() {
  createForm.value = { name: '', memberLimit: '', ownerUserId: null }
  try {
    const response = await api.users()
    // 所有人可选任意可用用户（含超管本人），超管在选项中标明
    candidates.value = response.data.items.filter(user => user.status === 1)
    const preferred = candidates.value.find(user => !user.is_super_admin) ?? candidates.value[0]
    if (preferred) createForm.value.ownerUserId = preferred.id
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '加载用户失败')
  }
  showCreateDialog.value = true
}

async function createTeam() {
  if (!createForm.value.name.trim() || !createForm.value.ownerUserId) {
    if (!createForm.value.ownerUserId) notice.error('请选择团队所有人')
    return
  }
  creating.value = true
  try {
    const rawLimit = String(createForm.value.memberLimit ?? '').trim()
    const limit = rawLimit === '' ? null : Number(rawLimit)
    await api.createTeam({
      name: createForm.value.name.trim(),
      owner_user_id: createForm.value.ownerUserId,
      member_limit: limit || null,
    })
    notice.success('团队已创建')
    showCreateDialog.value = false
    await loadTeams()
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '创建团队失败')
  } finally {
    creating.value = false
  }
}

async function topUp(team: TeamItem) {
  const amount = window.prompt(`为「${team.name}」充值金额（元）：`)
  const parsed = Number(amount)
  if (!amount || Number.isNaN(parsed) || parsed <= 0) return
  try {
    await api.teamTopUp({ team_id: team.id, amount: parsed, note: '管理端充值' })
    notice.success('充值成功')
    await loadTeams()
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '充值失败')
  }
}

async function toggleStatus(team: TeamItem) {
  try {
    await api.updateTeam(team.id, { status: team.status === 1 ? 0 : 1 })
    notice.success(team.status === 1 ? '团队已停用' : '团队已启用')
    await loadTeams()
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '操作失败')
  }
}

async function rename(team: TeamItem) {
  const name = window.prompt('新团队名称：', team.name)
  if (!name || !name.trim() || name.trim() === team.name) return
  try {
    await api.updateTeam(team.id, { name: name.trim() })
    notice.success('团队已改名')
    await loadTeams()
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '改名失败')
  }
}

async function setMemberLimit(team: TeamItem) {
  const raw = window.prompt(
    `「${team.name}」人员上限（留空或 0 表示不限）：`,
    team.member_limit === null || team.member_limit === undefined ? '' : String(team.member_limit),
  )
  if (raw === null) return
  const value = raw.trim() === '' ? null : Number(raw)
  if (value !== null && (Number.isNaN(value) || value < 1)) return
  try {
    await api.updateTeam(team.id, { member_limit: value === 0 ? null : value })
    notice.success('人员上限已更新')
    await loadTeams()
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '设置上限失败')
  }
}

onMounted(loadTeams)
</script>

<template>
  <main class="teams-page">
    <header class="page-header">
      <h1>团队管理</h1>
      <button type="button" class="primary-button" @click="openCreateDialog">新建团队</button>
    </header>

    <section class="panel">
      <p v-if="loading" class="dim">加载中…</p>
      <table v-else class="team-table">
        <thead>
          <tr><th>团队</th><th>所有人</th><th>成员数</th><th>人员上限</th><th>余额（元）</th><th>状态</th><th class="actions">操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="team in teams" :key="team.id" :class="{ 'is-disabled': team.status !== 1 }">
            <td class="team-name">{{ team.name }}</td>
            <td>{{ team.owner_username || '—' }}</td>
            <td>{{ team.member_count }}</td>
            <td>{{ team.member_limit === null || team.member_limit === undefined ? '不限' : team.member_limit }}</td>
            <td :class="{ 'is-overdraft': Number(team.balance) < 0 }">{{ Number(team.balance).toFixed(2) }}</td>
            <td><span class="status-badge" :class="team.status === 1 ? 'is-active' : 'is-stopped'">{{ statusLabel(team.status) }}</span></td>
            <td class="actions">
              <button type="button" class="ghost-button" @click="topUp(team)">充值</button>
              <RouterLink class="ghost-button link" :to="`/members?team_id=${team.id}`">成员</RouterLink>
              <button type="button" class="ghost-button" @click="setMemberLimit(team)">上限</button>
              <button type="button" class="ghost-button" @click="rename(team)">改名</button>
              <button type="button" class="danger-button" @click="toggleStatus(team)">{{ team.status === 1 ? '停用' : '启用' }}</button>
            </td>
          </tr>
        </tbody>
      </table>
      <AppPagination
        :page="page"
        :page-size="pageSize"
        :total="totalTeams"
        @page-change="changePage"
        @size-change="changePageSize"
      />
    </section>

    <div v-if="showCreateDialog" class="dialog-mask" @click.self="showCreateDialog = false">
      <form class="dialog-card" @submit.prevent="createTeam">
        <h2>新建团队</h2>
        <label>
          <span>团队名称</span>
          <input v-model="createForm.name" type="text" placeholder="团队名称" required />
        </label>
        <div class="owner-field">
          <span class="owner-field__label">所有人（将自动成为该团队管理员）</span>
          <AppSelect
            :model-value="createForm.ownerUserId ? String(createForm.ownerUserId) : ''"
            :options="ownerOptions"
            ariaLabel="选择团队所有人"
            @update:model-value="selectOwner"
          />
          <p v-if="!candidates.length" class="dim">没有可选用户，请先在「用户管理」中创建用户</p>
        </div>
        <label>
          <span>人员上限（留空表示不限）</span>
          <input v-model="createForm.memberLimit" type="number" min="1" placeholder="如 10" />
        </label>
        <div class="dialog-actions">
          <button type="button" class="ghost-button" @click="showCreateDialog = false">取消</button>
          <button type="submit" class="primary-button" :disabled="creating || !candidates.length">{{ creating ? '创建中…' : '创建' }}</button>
        </div>
      </form>
    </div>
  </main>
</template>

<style scoped>
.teams-page { max-width: 1080px; margin: 0 auto; padding: 28px 24px; display: flex; flex-direction: column; gap: 18px; }
.page-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.page-header h1 { margin: 0; font-size: 22px; color: var(--app-text, #303442); }
.primary-button { height: 36px; padding: 0 16px; border: none; border-radius: 8px; background: var(--app-accent, #5b5cf6); color: #fff; font-weight: 600; cursor: pointer; }
.primary-button:disabled { opacity: 0.6; }
.panel { background: var(--app-surface, #fff); border: 1px solid var(--app-border, #e3e5ec); border-radius: 12px; padding: 18px; }
.team-table { width: 100%; border-collapse: collapse; font-size: 13px; color: var(--app-text, #303442); }
.team-table th, .team-table td { text-align: left; padding: 10px; border-bottom: 1px solid var(--app-border, #e3e5ec); }
.team-table .actions { text-align: right; white-space: nowrap; }
.team-name { font-weight: 600; }
.is-disabled { opacity: 0.6; }
.is-overdraft { color: var(--app-danger, #dc2626); font-weight: 600; }
.status-badge { padding: 2px 8px; border-radius: 999px; font-size: 12px; }
.status-badge.is-active { background: var(--app-success-soft, rgba(16, 185, 129, 0.12)); color: var(--app-success, #059669); }
.status-badge.is-stopped { background: var(--app-danger-soft, rgba(220, 38, 38, 0.1)); color: var(--app-danger, #dc2626); }
.ghost-button, .danger-button { display: inline-flex; align-items: center; height: 28px; padding: 0 10px; border-radius: 8px; font-size: 12px; cursor: pointer; border: 1px solid var(--app-border, #e3e5ec); background: transparent; color: var(--app-text-muted, #9398a8); text-decoration: none; margin-left: 6px; }
.danger-button { color: var(--app-danger, #dc2626); }
.dim { color: var(--app-text-muted, #9398a8); font-size: 13px; }
.dialog-mask { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); display: flex; align-items: center; justify-content: center; z-index: 100; }
.dialog-card { width: 100%; max-width: 380px; background: var(--app-surface, #fff); border-radius: 14px; padding: 24px; display: flex; flex-direction: column; gap: 14px; }
.dialog-card h2 { margin: 0; font-size: 17px; color: var(--app-text, #303442); }
.dialog-card label { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: var(--app-text-muted, #9398a8); }
.owner-field { display: flex; flex-direction: column; gap: 6px; }
.owner-field__label { font-size: 13px; color: var(--app-text-muted, #9398a8); }
.dialog-card input, .dialog-card select { height: 36px; padding: 0 10px; border: 1px solid var(--app-border, #e3e5ec); border-radius: 8px; background: var(--app-surface-muted, #f2f3f7); color: var(--app-text, #303442); font-size: 13px; }
.dialog-actions { display: flex; justify-content: flex-end; gap: 8px; }
.dialog-card .dialog-actions :is(.ghost-button,.primary-button) { height: 36px; padding: 0 16px; font-size: 13px; margin-left: 0; }
</style>
