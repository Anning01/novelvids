<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Download, RefreshCw } from 'lucide-vue-next'
import { api, statusLabel } from '@/api'
import { tr } from '@/i18n'
import AppButton from '@/components/AppButton.vue'
import AppSelect from '@/components/AppSelect.vue'
import AppPagination from '@/components/AppPagination.vue'
import { usageLabel } from './recordDisplay'
import { notice } from '@/shared/notice'
import type { BillingStatement, BillingStatementFilters, BillingStatementParties, BillingStatementRow } from '@/types'

const parties = ref<BillingStatementParties>({ teams: [], users: [] })
const partyError = ref('')
const team = ref('')
const user = ref('')
const start = ref('')
const end = ref('')
const page = ref(1)
const pageSize = ref(20)
const data = ref<BillingStatement | null>(null)
const loading = ref(false)
const exporting = ref(false)
const error = ref('')
let epoch = 0
let appliedFilters: BillingStatementFilters = {}
const invalidDates = computed(() => Boolean(start.value && end.value && start.value > end.value))
const teamOptions = computed(() => [{ value: '', label: tr('全部团队') }, ...parties.value.teams.map(t => ({ value: String(t.id), label: `${t.name} (#${t.id})` }))])
const userOptions = computed(() => [{ value: '', label: tr('全部用户') }, ...parties.value.users.map(u => ({ value: String(u.id), label: `${u.name} (#${u.id})` }))])
const filters = (): BillingStatementFilters => ({ team_id: team.value ? Number(team.value) : undefined,
  user_id: user.value ? Number(user.value) : undefined, start_date: start.value || undefined, end_date: end.value || undefined })
const category = (value: string | null) => ({ text: tr('文本'), image: tr('生图'), video: tr('视频'), media_processing: tr('画质增强'), asr: tr('语音识别') })[value || ''] || '—'
const exactMoney = (value: string | null | undefined) => value == null ? '—' : `¥${value}`
const rowUsage = (row: BillingStatementRow) => row.billing_type ? usageLabel({ ...row, billing_type: row.billing_type }) : '—'

async function load(reset = false) {
  const current = ++epoch
  if (reset) page.value = 1
  if (invalidDates.value) { loading.value = false; return }
  loading.value = true
  error.value = ''
  const selected = { ...filters(), snapshot_id: reset ? undefined : data.value?.snapshot_id }
  try {
    const response = await api.billingStatements({ ...selected, page: page.value, page_size: pageSize.value })
    if (current !== epoch) return
    data.value = response.data
    appliedFilters = { ...selected, snapshot_id: response.data.snapshot_id }
  } catch (reason) {
    if (current === epoch) { data.value = null; error.value = reason instanceof Error ? reason.message : tr('账单加载失败') }
  } finally {
    if (current === epoch) loading.value = false
  }
}
async function loadParties() {
  partyError.value = ''
  try { parties.value = (await api.billingStatementParties()).data }
  catch (reason) { partyError.value = reason instanceof Error ? reason.message : tr('筛选选项加载失败') }
}
async function exportStatement() {
  exporting.value = true
  try {
    await api.exportBillingStatement({ ...appliedFilters })
    notice.success(tr('账单已导出'))
  } catch (reason) { notice.error(reason instanceof Error ? reason.message : tr('导出失败')) }
  finally { exporting.value = false }
}
function changePage(next: number) { page.value = next; void load() }
function changeSize(next: number) { pageSize.value = next; page.value = 1; void load() }
watch([team, user, start, end], () => { void load(true) })
onMounted(() => { void loadParties(); void load(true) })
onBeforeUnmount(() => { epoch += 1 })
</script>

<template>
  <section class="billing-statements" :aria-label="tr('消费账单')">
    <div class="statement-toolbar">
      <div class="statement-filters">
        <label><span>{{ tr('团队') }}</span><AppSelect v-model="team" :options="teamOptions" :ariaLabel="tr('账单团队')" searchable /></label>
        <label><span>{{ tr('用户') }}</span><AppSelect v-model="user" :options="userOptions" :ariaLabel="tr('账单用户')" searchable /></label>
        <label><span>{{ tr('开始日期') }}</span><input v-model="start" type="date" :aria-label="tr('开始日期')" :max="end || undefined" /></label>
        <label><span>{{ tr('结束日期') }}</span><input v-model="end" type="date" :aria-label="tr('结束日期')" :min="start || undefined" /></label>
      </div>
      <div class="statement-actions">
        <AppButton variant="secondary" :disabled="loading || invalidDates" @click="load(true)"><RefreshCw :size="14" aria-hidden="true" />{{ tr('刷新') }}</AppButton>
        <AppButton variant="primary" :loading="exporting" :disabled="loading || invalidDates || !!error || !data?.summary.total_transactions" @click="exportStatement"><Download :size="14" aria-hidden="true" />{{ tr('导出全部明细') }}</AppButton>
      </div>
    </div>
    <p v-if="partyError" class="statement-error" role="alert">{{ partyError }} <AppButton size="sm" @click="loadParties">{{ tr('重试') }}</AppButton></p>
    <p v-if="invalidDates" class="statement-error" role="alert">{{ tr('开始日期不能晚于结束日期') }}</p>
    <div v-else-if="loading" class="statement-state" role="status">{{ tr('正在读取账单…') }}</div>
    <div v-else-if="error" class="statement-state" role="alert">{{ error }} <AppButton @click="load(true)">{{ tr('重试') }}</AppButton></div>
    <template v-else-if="data">
      <div class="statement-summary">
        <article><span>{{ tr('实际扣款') }}</span><strong>{{ exactMoney(data.summary.total_cost) }}</strong></article>
        <article><span>{{ tr('扣款笔数') }}</span><strong>{{ data.summary.total_transactions }}</strong></article>
        <article><span>{{ tr('团队当前余额') }}</span><strong>{{ exactMoney(data.summary.team_balance) }}</strong><small v-if="!team">{{ tr('选择团队后显示') }}</small></article>
      </div>
      <p class="statement-note">{{ tr('仅列出实际余额扣款。未扣款任务和自有 Key 用量不计入；金额保留6位小数，时间为北京时间。') }}</p>
      <div class="statement-table-scroll">
        <table class="statement-table">
          <thead><tr><th>{{ tr('流水号') }}</th><th>{{ tr('时间') }}</th><th>{{ tr('团队') }}</th><th>{{ tr('用户') }}</th><th>{{ tr('项目') }}</th><th>{{ tr('费用类别') }}</th><th>{{ tr('用量') }}</th><th>{{ tr('任务状态') }}</th><th class="is-num">{{ tr('实际扣款') }}</th><th class="is-num">{{ tr('扣后团队余额') }}</th></tr></thead>
          <tbody>
            <tr v-for="row in data.items" :key="row.id">
              <td class="statement-id">#{{ row.id }}<small v-if="row.usage_record_id">{{ tr('账单号') }} #{{ row.usage_record_id }}</small></td>
              <td>{{ row.created_at }}</td>
              <td>{{ row.team_name }}<small>#{{ row.team_id }}</small></td>
              <td>{{ row.user_name || tr('用户未记录') }}<small v-if="row.user_id">#{{ row.user_id }}</small></td>
              <td>{{ row.novel_name || '—' }}<small v-if="row.novel_id">#{{ row.novel_id }}</small></td>
              <td>{{ category(row.billing_type) }}<small v-if="row.video_id">{{ tr('视频') }} #{{ row.video_id }}</small></td>
              <td>{{ rowUsage(row) }}</td>
              <td>{{ row.task_status == null ? tr('未记录') : statusLabel(row.task_status) }}</td>
              <td class="is-num">{{ exactMoney(row.cost) }}</td><td class="is-num">{{ exactMoney(row.balance_after) }}</td>
            </tr>
            <tr v-if="!data.items.length"><td colspan="10" class="statement-empty">{{ tr('当前范围暂无扣款记录') }}</td></tr>
          </tbody>
        </table>
      </div>
      <AppPagination :page="page" :page-size="pageSize" :total="data.pagination.total" :page-size-options="[20, 50, 100]" @page-change="changePage" @size-change="changeSize" />
    </template>
  </section>
</template>

<style scoped>
.billing-statements { margin-top: 22px; }
.statement-toolbar, .statement-filters, .statement-actions { display: flex; align-items: flex-end; gap: 12px; flex-wrap: wrap; }
.statement-toolbar { justify-content: space-between; margin-bottom: 20px; }
.statement-filters > label { display: grid; gap: 6px; min-width: 150px; color: var(--app-text-secondary); font-size: 12px; }
.statement-filters > label:nth-child(-n+2) { width: 215px; }
input { box-sizing: border-box; min-height: 38px; max-width: 100%; padding: 6px 10px; border: 1px solid var(--app-border); border-radius: 9px; color: var(--app-text); background: var(--app-surface-raised); font: inherit; }
input:hover { border-color: var(--app-border-strong); }
input:focus-visible { outline: 2px solid var(--app-accent); outline-offset: 2px; }
.statement-summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.statement-summary article { display: grid; gap: 10px; align-content: start; padding: 18px; border: 1px solid var(--app-border); border-radius: 12px; background: var(--app-surface-raised); }
.statement-summary span, .statement-note, small { color: var(--app-text-muted); font-size: 12px; }
.statement-summary strong { font-size: 25px; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.statement-note { margin: 15px 0; line-height: 1.7; }
.statement-table-scroll { overflow-x: auto; border: 1px solid var(--app-border); border-radius: 12px; background: var(--app-surface-raised); }
.statement-table { width: 100%; border-collapse: collapse; font-size: 12px; white-space: nowrap; }
th, td { padding: 14px 16px; border-bottom: 1px solid var(--app-border); text-align: left; }
th { background: var(--app-surface-muted); color: var(--app-text-secondary); font-weight: 600; }
tbody tr:last-child td { border-bottom: 0; }
tbody tr:hover { background: var(--app-surface-hover); }
td small { display: block; margin-top: 5px; }
.is-num { text-align: right; font-variant-numeric: tabular-nums; }
.statement-state, .statement-empty { padding: 48px 16px; color: var(--app-text-muted); text-align: center; }
.statement-error { color: var(--app-danger, var(--app-text)); font-size: 13px; }
:global([data-app-theme='dark']) input { color-scheme: dark; }
@media (max-width: 640px) { .statement-summary { grid-template-columns: 1fr; } .statement-filters { width: 100%; } .statement-filters > label, .statement-filters > label:nth-child(-n+2) { flex: 1 1 calc(50% - 12px); min-width: 0; width: auto; } }
</style>
