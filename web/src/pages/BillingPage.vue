<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Activity, Clapperboard, Coins, Image, Type, ChevronRight } from 'lucide-vue-next'
import AppSelect from '@/components/AppSelect.vue'
import { api } from '@/api'
import BillingRecordDetails from '@/features/billing/BillingRecordDetails.vue'
import { costSourceLabel, money, recordStatus, usageLabel } from '@/features/billing/recordDisplay'
import { useAuthStore } from '@/features/auth/authStore'
import { notice } from '@/shared/notice'
import type { BillingProject, BillingRecord, BillingSummary } from '@/types'

const summary = ref<BillingSummary | null>(null)
const projects = ref<BillingProject[]>([])
const records = ref<BillingRecord[]>([])
const totalRecords = ref(0)
const loading = ref(true)
const page = ref(1)
const pageSize = ref(20)
const selectedProjectId = ref('all')
const expandedRecordId = ref<number | null>(null)
const auth = useAuthStore()
const showSourceColumn = computed(() => auth.enabled === true)

const billingTypeLabel = (value: string) => ({ text: '文本', image: '生图', video: '视频' }[value] || value)
const taskTypeLabel = (value: number) => ({ 1: '提取', 2: '参考图', 3: '分镜', 4: '视频', 5: '项目分析', 6: '重制', 7: '创作助手' }[value] || `任务 ${value}`)

function recordDiscount(item: BillingRecord): number {
  if (item.record_kind === 'agent_conversation') return 1
  const snapshot = item.pricing_snapshot as Record<string, unknown> | null | undefined
  const raw = snapshot?.discount
  const value = Number(raw)
  return Number.isFinite(value) && value > 0 && value !== 1 ? value : 1
}
function discountText(discount: number): string {
  if (discount < 1) return `${Math.round(discount * 100) / 10}折`
  return `${discount}×`
}

const projectOptions = computed(() => [
  { value: 'all', label: '全部项目' },
  ...projects.value.map(item => ({ value: String(item.novel_id), label: item.novel_name })),
])
const selectedProject = computed(() => (
  projects.value.find(item => String(item.novel_id) === selectedProjectId.value) || null
))
const billingBreakdown = computed(() => {
  const map: Record<string, number> = { text: 0, image: 0, video: 0 }
  for (const item of summary.value?.by_billing_type ?? []) map[item.billing_type] = item.cost
  return map
})
const projectName = (novelId: number) => (
  projects.value.find(item => item.novel_id === novelId)?.novel_name || `项目 ${novelId}`
)
const pages = computed(() => Math.max(1, Math.ceil(totalRecords.value / pageSize.value)))

function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return '—'
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const minutes = Math.floor(seconds / 60)
  return `${minutes}m ${Math.round(seconds % 60)}s`
}

function currentNovelId(): number | undefined {
  return selectedProjectId.value === 'all' ? undefined : Number(selectedProjectId.value)
}

async function load() {
  expandedRecordId.value = null
  loading.value = true
  try {
    const novelId = currentNovelId()
    const [summaryResponse, projectsResponse, recordsResponse] = await Promise.all([
      api.billingSummary(novelId),
      api.billingProjects(1, 100),
      api.billingRecords({ novel_id: novelId, page: page.value, page_size: pageSize.value }),
    ])
    summary.value = summaryResponse.data
    projects.value = projectsResponse.data.items
    records.value = recordsResponse.data.items
    totalRecords.value = recordsResponse.data.pagination.total
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

async function loadRecords() {
  expandedRecordId.value = null
  loading.value = true
  try {
    const response = await api.billingRecords({ novel_id: currentNovelId(), page: page.value, page_size: pageSize.value })
    records.value = response.data.items
    totalRecords.value = response.data.pagination.total
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

function selectProject(novelId: string) {
  selectedProjectId.value = novelId
  page.value = 1
  void load()
}

function changePage(next: number) {
  page.value = next
  void loadRecords()
}

function changePageSize() {
  page.value = 1
  void loadRecords()
}

onMounted(load)
</script>

<template>
  <main class="billing-page">
    <header class="billing-header">
      <div>
        <span>COST DASHBOARD</span>
        <h1>成本看板</h1>
        <p>每个模型的调用成本，按项目与维度汇总。</p>
      </div>
      <AppSelect
        v-model="selectedProjectId"
        class="billing-project-filter"
        :options="projectOptions"
        ariaLabel="按项目过滤成本看板"
        @update:model-value="selectProject"
      />
    </header>

    <div v-if="loading" class="billing-state">正在读取成本数据…</div>
    <template v-else>
      <section class="summary-grid" aria-label="成本汇总">
        <article class="stat-card is-primary">
          <span class="stat-label"><Coins :size="15" />总成本</span>
          <strong class="stat-value">{{ money(summary?.total_cost ?? 0) }}</strong>
          <small class="stat-sub">{{ selectedProject ? selectedProject.novel_name : '全部项目累计' }}</small>
        </article>
        <article class="stat-card">
          <span class="stat-label"><Activity :size="15" />计费记录</span>
          <strong class="stat-value">{{ summary?.total_records ?? 0 }}</strong>
          <small class="stat-sub">条原始用量记录</small>
        </article>
        <article class="stat-card is-text">
          <span class="stat-label"><Type :size="15" />文本</span>
          <strong class="stat-value">{{ money(billingBreakdown.text) }}</strong>
        </article>
        <article class="stat-card is-image">
          <span class="stat-label"><Image :size="15" />生图</span>
          <strong class="stat-value">{{ money(billingBreakdown.image) }}</strong>
        </article>
        <article class="stat-card is-video">
          <span class="stat-label"><Clapperboard :size="15" />视频</span>
          <strong class="stat-value">{{ money(billingBreakdown.video) }}</strong>
        </article>
      </section>

      <section class="table-card">
        <header class="table-card__header">
          <div><h2>调用流水</h2><p>创作助手按会话汇总，展开可查看明细。</p></div>
          <small>{{ selectedProject?.novel_name || '全部项目' }}</small>
        </header>
        <table class="data-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>项目</th>
              <th>维度</th>
              <th>任务</th>
              <th>模型</th>
              <th>用量</th>
              <th>时长</th>
              <th>状态</th>
              <th v-if="showSourceColumn">来源</th>
              <th class="is-num">成本</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="item in records" :key="item.id"><tr>
              <td class="cell-muted">{{ item.created_at }}</td>
              <td>{{ projectName(item.novel_id) }}</td>
              <td>{{ billingTypeLabel(item.billing_type) }}</td>
              <td><template v-if="item.record_kind === 'agent_conversation'">
                <button class="conversation-record-toggle" type="button" :aria-label="`查看会话 ${item.conversation_id} 费用明细`" :aria-expanded="expandedRecordId === item.id" :aria-controls="`billing-details-${item.id}`" @click="expandedRecordId = expandedRecordId === item.id ? null : item.id">
                  <ChevronRight :size="13" :class="{ 'is-expanded': expandedRecordId === item.id }" />创作助手
                </button><small class="conversation-record-meta">会话 {{ item.conversation_id }} · {{ item.turn_count }} 轮对话</small>
              </template><template v-else>{{ taskTypeLabel(item.task_type) }}</template></td>
              <td>{{ item.model_name || item.model }}</td>
              <td class="cell-muted">{{ usageLabel(item) }}</td>
              <td class="cell-mono">{{ formatDuration(item.duration_seconds) }}</td>
              <td>{{ recordStatus(item) }}</td>
              <td v-if="showSourceColumn">
                <span class="source-badge" :class="{ 'is-key': item.cost_source === 'team_key', 'is-balance': item.cost_source === 'balance' }">{{ costSourceLabel(item.cost_source) }}</span>
              </td>
              <td class="is-num cell-mono">
                <div v-if="recordDiscount(item) !== 1" class="cost-with-discount">
                  <span class="list-price">{{ money(item.cost / recordDiscount(item), item.currency) }}</span>
                  <span class="discount-chip">{{ discountText(recordDiscount(item)) }}</span>
                </div>
                {{ money(item.cost, item.currency) }}
              </td>
            </tr>
            <tr v-if="expandedRecordId === item.id" :id="`billing-details-${item.id}`" class="conversation-record-detail"><td :colspan="showSourceColumn ? 10 : 9">
              <BillingRecordDetails :record-id="item.id" :novel-id="item.novel_id" :show-source="showSourceColumn" />
            </td></tr></template>
            <tr v-if="!records.length"><td :colspan="showSourceColumn ? 10 : 9" class="empty">暂无调用记录</td></tr>
          </tbody>
        </table>
        <footer v-if="totalRecords > 0" class="pager">
          <span class="pager-total">共 {{ totalRecords }} 条</span>
          <div class="pager-controls">
            <select v-model.number="pageSize" class="pager-size" aria-label="每页条数" @change="changePageSize">
              <option :value="20">20 条/页</option>
              <option :value="50">50 条/页</option>
              <option :value="100">100 条/页</option>
            </select>
            <button type="button" :disabled="page <= 1" @click="changePage(page - 1)">上一页</button>
            <span>{{ page }} / {{ pages }}</span>
            <button type="button" :disabled="page >= pages" @click="changePage(page + 1)">下一页</button>
          </div>
        </footer>
      </section>
    </template>
  </main>
</template>

<style scoped>
.billing-page { min-height: 100%; padding: 36px 24px 80px; color: var(--app-text); background: var(--app-surface); }
.billing-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 26px; }
.billing-header span { color: var(--app-accent); font-size: 9px; font-weight: 750; letter-spacing: .16em; }
.billing-header h1 { margin: 4px 0 0; font-size: 30px; letter-spacing: -.03em; }
.billing-header p { margin: 5px 0 0; color: var(--app-text-muted); font-size: 12px; }
.billing-project-filter { width: 240px; }
.billing-state { padding: 60px 0; color: var(--app-text-muted); text-align: center; }

.summary-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin-bottom: 26px; }
.stat-card { display: grid; align-content: start; gap: 9px; padding: 18px 18px 16px; border-radius: 16px; background: linear-gradient(180deg, var(--app-surface-raised, #fff), var(--app-surface-muted, #f2f3f7)); box-shadow: inset 0 0 0 1px var(--app-border, #eceef3), 0 1px 2px rgb(20 22 28 / 3%), 0 10px 28px rgb(20 22 28 / 5%); }
.stat-card.is-primary { background: linear-gradient(180deg, color-mix(in srgb, #5b5cf6 16%, var(--app-surface-raised, #fff)), color-mix(in srgb, #5b5cf6 10%, var(--app-surface-muted, #f2f3f7))); }
.stat-card.is-text { background: linear-gradient(180deg, color-mix(in srgb, #5b5cf6 9%, var(--app-surface-raised, #fff)), var(--app-surface-muted, #f2f3f7)); }
.stat-card.is-image { background: linear-gradient(180deg, color-mix(in srgb, #22a06b 9%, var(--app-surface-raised, #fff)), var(--app-surface-muted, #f2f3f7)); }
.stat-card.is-video { background: linear-gradient(180deg, color-mix(in srgb, #e08a3c 11%, var(--app-surface-raised, #fff)), var(--app-surface-muted, #f2f3f7)); }
.stat-label { display: inline-flex; align-items: center; gap: 6px; color: var(--app-text-muted); font-size: 11px; font-weight: 600; }
.is-primary .stat-label, .stat-card.is-text .stat-label { color: #5b5cf6; }
.stat-card.is-image .stat-label { color: #22a06b; }
.stat-card.is-video .stat-label { color: #e08a3c; }
.stat-value { font-size: 26px; font-weight: 720; letter-spacing: -.02em; line-height: 1; font-variant-numeric: tabular-nums; }
.is-primary .stat-value { font-size: 30px; }
.stat-sub { color: var(--app-text-muted); font-size: 10px; }

:global([data-app-theme='dark']) .stat-card.is-primary .stat-label,
:global([data-app-theme='dark']) .stat-card.is-text .stat-label { color: #9ba9ff; }
:global([data-app-theme='dark']) .stat-card.is-image .stat-label { color: #4ed8a0; }
:global([data-app-theme='dark']) .stat-card.is-video .stat-label { color: #f2b26b; }

.table-card { margin-bottom: 22px; border-radius: 16px; background: var(--app-surface-raised, #fff); box-shadow: 0 1px 2px rgb(20 22 28 / 3%), 0 10px 28px rgb(20 22 28 / 5%); overflow: hidden; }
.table-card__header { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; padding: 16px 20px 12px; }
.table-card__header h2 { margin: 0; font-size: 14px; }
.table-card__header p { margin: 5px 0 0; color: var(--app-text-muted); font-size: 11px; }
.conversation-record-toggle { display: inline-flex; align-items: center; gap: 4px; padding: 3px 0; border: 0; background: transparent; color: var(--app-accent); font: inherit; cursor: pointer; white-space: nowrap; }
.conversation-record-toggle:focus-visible { outline: 2px solid var(--app-accent); outline-offset: 2px; border-radius: 4px; }
.conversation-record-toggle svg { transition: transform .18s; }.conversation-record-toggle .is-expanded { transform: rotate(90deg); }
.conversation-record-meta { display: block; color: var(--app-text-muted); font-size: 10px; margin-top: 2px; white-space: nowrap; }
.data-table .conversation-record-detail > td { padding: 0; }
@media (prefers-reduced-motion: reduce) { .conversation-record-toggle svg { transition: none; } }
.table-card__header small { color: var(--app-text-muted); font-size: 11px; }
.data-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.data-table th, .data-table td { padding: 11px 20px; text-align: left; }
.data-table thead th { color: var(--app-text-muted); font-weight: 650; font-size: 10px; letter-spacing: .04em; border-bottom: 1px solid var(--app-border); }
.data-table tbody tr { transition: background-color .12s ease; }
.data-table tbody tr:hover { background: var(--app-surface-hover, #f7f8fb); }
.data-table tbody td { border-bottom: 1px solid var(--app-border); }
.data-table tbody tr:last-child td { border-bottom: 0; }
.data-table .is-num { text-align: right; }
.data-table .cell-muted { color: var(--app-text-muted); }
.data-table .cell-mono { font-variant-numeric: tabular-nums; }
.data-table .empty { color: var(--app-text-muted); text-align: center; padding: 28px; }

.source-badge { padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; }
.source-badge.is-balance { color: var(--app-accent); background: var(--app-accent-soft); }
.source-badge.is-key { color: #059669; background: rgb(16 185 129 / 12%); }
.cost-with-discount { display: flex; align-items: center; justify-content: flex-end; gap: 6px; margin-bottom: 2px; }
.cost-with-discount .list-price { color: var(--app-text-muted); text-decoration: line-through; font-size: 11px; }
.cost-with-discount .discount-chip { padding: 1px 6px; border-radius: 999px; font-size: 10px; font-weight: 600; color: #b45309; background: rgb(245 158 11 / 15%); }
.pager { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 20px 16px; }
.pager-total { color: var(--app-text-muted); font-size: 11px; }
.pager-controls { display: flex; align-items: center; gap: 10px; }
.pager span { color: var(--app-text-muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.pager button { padding: 6px 12px; border: 1px solid var(--app-border); border-radius: 8px; color: var(--app-text-secondary); background: var(--app-surface); cursor: pointer; font-size: 11px; }
.pager button:hover:not(:disabled) { color: var(--app-text); background: var(--app-surface-hover); }
.pager button:disabled { opacity: .45; cursor: not-allowed; }
.pager-size { height: 30px; padding: 0 8px; border: 1px solid var(--app-border); border-radius: 8px; color: var(--app-text-secondary); background: var(--app-surface); font-size: 11px; cursor: pointer; }

@media (max-width: 960px) {
  .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  .billing-header { align-items: stretch; flex-direction: column; }
  .billing-project-filter { width: 100%; }
  .summary-grid { grid-template-columns: 1fr 1fr; }
  .data-table th, .data-table td { padding: 10px 14px; }
}
</style>
