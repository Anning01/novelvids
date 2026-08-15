<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { BarChart3, Coins, ListOrdered } from 'lucide-vue-next'
import { api, statusLabel } from '@/api'
import { notice } from '@/shared/notice'
import type { BillingProject, BillingRecord, BillingSummary } from '@/types'

const summary = ref<BillingSummary | null>(null)
const projects = ref<BillingProject[]>([])
const records = ref<BillingRecord[]>([])
const totalRecords = ref(0)
const loading = ref(true)
const page = ref(1)
const pageSize = 20

const billingTypeLabel = (value: string) => ({ text: '文本', image: '生图', video: '视频' }[value] || value)
const taskTypeLabel = (value: number) => ({ 1: '提取', 2: '参考图', 3: '分镜', 4: '视频', 5: '项目分析' }[value] || `任务 ${value}`)
const money = (value: number) => `¥ ${value.toFixed(6)}`

async function load() {
  loading.value = true
  try {
    const [summaryResponse, projectsResponse, recordsResponse] = await Promise.all([
      api.billingSummary(),
      api.billingProjects(1, 100),
      api.billingRecords({ page: page.value, page_size: pageSize }),
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

async function changePage(next: number) {
  page.value = next
  await load()
}

onMounted(load)
</script>

<template>
  <main class="billing-page">
    <header class="billing-header">
      <span>COST DASHBOARD</span>
      <h1>成本看板</h1>
      <p>每个模型的调用成本，按项目与维度汇总。</p>
    </header>

    <div v-if="loading" class="billing-state">正在读取成本数据…</div>
    <template v-else>
      <section class="summary-grid">
        <article class="summary-card">
          <Coins :size="20" />
          <span>总成本</span>
          <strong>{{ summary ? money(summary.total_cost) : '¥ 0.000000' }}</strong>
        </article>
        <article class="summary-card">
          <ListOrdered :size="20" />
          <span>调用次数</span>
          <strong>{{ summary?.total_records ?? 0 }}</strong>
        </article>
        <article class="summary-card">
          <BarChart3 :size="20" />
          <span>计费维度</span>
          <ul>
            <li v-for="item in summary?.by_billing_type ?? []" :key="item.billing_type">
              {{ billingTypeLabel(item.billing_type) }} · {{ money(item.cost) }}
            </li>
          </ul>
        </article>
      </section>

      <section class="panel">
        <header><h2>项目成本</h2></header>
        <table class="data-table">
          <thead><tr><th>项目</th><th>调用次数</th><th>成本</th></tr></thead>
          <tbody>
            <tr v-for="item in projects" :key="item.novel_id">
              <td>{{ item.novel_name }}</td>
              <td>{{ item.record_count }}</td>
              <td>{{ money(item.total_cost) }}</td>
            </tr>
            <tr v-if="!projects.length"><td colspan="3" class="empty">暂无计费数据</td></tr>
          </tbody>
        </table>
      </section>

      <section class="panel">
        <header><h2>调用流水</h2></header>
        <table class="data-table">
          <thead><tr><th>时间</th><th>维度</th><th>任务</th><th>模型</th><th>状态</th><th>成本</th></tr></thead>
          <tbody>
            <tr v-for="item in records" :key="item.id">
              <td>{{ item.created_at }}</td>
              <td>{{ billingTypeLabel(item.billing_type) }}</td>
              <td>{{ taskTypeLabel(item.task_type) }}</td>
              <td>{{ item.model_name || item.model }}</td>
              <td>{{ statusLabel(item.status) }}</td>
              <td>{{ money(item.cost) }}</td>
            </tr>
            <tr v-if="!records.length"><td colspan="6" class="empty">暂无调用记录</td></tr>
          </tbody>
        </table>
        <footer v-if="totalRecords > pageSize" class="pager">
          <button type="button" :disabled="page <= 1" @click="changePage(page - 1)">上一页</button>
          <span>{{ page }} / {{ Math.ceil(totalRecords / pageSize) }}</span>
          <button type="button" :disabled="page >= Math.ceil(totalRecords / pageSize)" @click="changePage(page + 1)">下一页</button>
        </footer>
      </section>
    </template>
  </main>
</template>

<style scoped>
.billing-page { min-height: 100%; padding: 36px 22px 80px; color: var(--app-text); background: var(--app-surface); }
.billing-header { margin-bottom: 28px; padding-bottom: 28px; border-bottom: 1px solid var(--app-border); }
.billing-header span { color: var(--app-accent); font-size: 9px; font-weight: 750; letter-spacing: .16em; }
.billing-header h1 { margin: 4px 0 0; font-size: 30px; letter-spacing: -.03em; }
.billing-header p { margin: 4px 0 0; color: var(--app-text-muted); font-size: 12px; }
.billing-state { padding: 60px 0; color: var(--app-text-muted); text-align: center; }
.summary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 24px; }
.summary-card { display: grid; gap: 6px; padding: 18px; border: 1px solid var(--app-border); border-radius: 14px; background: var(--app-surface-muted); }
.summary-card > svg { color: var(--app-accent); }
.summary-card span { color: var(--app-text-muted); font-size: 11px; }
.summary-card strong { font-size: 22px; }
.summary-card ul { display: grid; gap: 4px; margin: 0; padding: 0; list-style: none; color: var(--app-text-secondary); font-size: 11px; }
.panel { margin-bottom: 24px; border: 1px solid var(--app-border); border-radius: 14px; overflow: hidden; }
.panel > header { padding: 14px 18px; border-bottom: 1px solid var(--app-border); }
.panel h2 { margin: 0; font-size: 14px; }
.data-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.data-table th, .data-table td { padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--app-border); }
.data-table th { color: var(--app-text-muted); font-weight: 600; font-size: 10px; }
.data-table .empty { color: var(--app-text-muted); text-align: center; padding: 24px; }
.pager { display: flex; align-items: center; justify-content: flex-end; gap: 12px; padding: 12px 18px; }
.pager button { padding: 6px 12px; border: 1px solid var(--app-border); border-radius: 8px; background: var(--app-surface-muted); cursor: pointer; }
.pager button:disabled { opacity: .5; cursor: not-allowed; }
@media (max-width: 720px) { .summary-grid { grid-template-columns: 1fr; } }
</style>
