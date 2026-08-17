<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Activity, Clapperboard, Coins, Image, Type } from 'lucide-vue-next'
import AppSelect from '@/components/AppSelect.vue'
import { api, statusLabel } from '@/api'
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
const auth = useAuthStore()
const showSourceColumn = computed(() => auth.enabled === true)
function costSourceLabel(source?: string) {
  if (source === 'team_key') return '团队 Key'
  if (source === 'balance') return '团队余额'
  return '平台'
}

const billingTypeLabel = (value: string) => ({ text: '文本', image: '生图', video: '视频' }[value] || value)
const taskTypeLabel = (value: number) => ({ 1: '提取', 2: '参考图', 3: '分镜', 4: '视频', 5: '项目分析' }[value] || `任务 ${value}`)

function money(value: number): string {
  if (!value) return '¥0'
  const abs = Math.abs(value)
  if (abs >= 1) return `¥${value.toFixed(2)}`
  if (abs >= 0.01) return `¥${value.toFixed(4)}`
  return `¥${value.toFixed(6)}`
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

function formatTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`
  return String(value)
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return '—'
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const minutes = Math.floor(seconds / 60)
  return `${minutes}m ${Math.round(seconds % 60)}s`
}

function usageLabel(item: BillingRecord): string {
  const usage = item.usage || {}
  const num = (value: unknown) => Number(value) || 0
  if (item.billing_type === 'text') {
    return `输入 ${formatTokens(num(usage.input_tokens))} · 输出 ${formatTokens(num(usage.output_tokens))} token`
  }
  if (item.billing_type === 'image') {
    const count = num(usage.image_count)
    const clarity = usage.clarity ? ` @${usage.clarity}` : ''
    const input = num(usage.input_image_count)
    return `${count} 张${clarity}${input ? ` · 输入 ${input} 张` : ''}`
  }
  const seconds = num(usage.seconds)
  const resolution = usage.resolution ? ` @${usage.resolution}` : ''
  const input = num(usage.input_video_seconds)
  return `${seconds}s${resolution}${input ? ` · 参考 ${input}s` : ''}`
}

function currentNovelId(): number | undefined {
  return selectedProjectId.value === 'all' ? undefined : Number(selectedProjectId.value)
}

async function load() {
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
          <span class="stat-label"><Activity :size="15" />调用次数</span>
          <strong class="stat-value">{{ summary?.total_records ?? 0 }}</strong>
          <small class="stat-sub">次模型调用</small>
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
          <h2>调用流水</h2>
          <small v-if="selectedProject">{{ selectedProject.novel_name }}</small>
          <small v-else>全部项目</small>
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
            <tr v-for="item in records" :key="item.id">
              <td class="cell-muted">{{ item.created_at }}</td>
              <td>{{ projectName(item.novel_id) }}</td>
              <td>{{ billingTypeLabel(item.billing_type) }}</td>
              <td>{{ taskTypeLabel(item.task_type) }}</td>
              <td>{{ item.model_name || item.model }}</td>
              <td class="cell-muted">{{ usageLabel(item) }}</td>
              <td class="cell-mono">{{ formatDuration(item.duration_seconds) }}</td>
              <td>{{ statusLabel(item.status) }}</td>
              <td v-if="showSourceColumn">
                <span class="source-badge" :class="item.cost_source === 'team_key' ? 'is-key' : 'is-balance'">{{ costSourceLabel(item.cost_source) }}</span>
              </td>
              <td class="is-num cell-mono">{{ money(item.cost) }}</td>
            </tr>
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
