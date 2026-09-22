<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { api } from '@/api'
import AppButton from '@/components/AppButton.vue'
import type { BillingRecord } from '@/types'
import { costSourceLabel, money, recordStatus, usageLabel } from './recordDisplay'

const props = defineProps<{ recordId: number; novelId: number; showSource: boolean }>()
const records = ref<BillingRecord[]>([])
const loading = ref(false)
const error = ref('')
const page = ref(1)
const pages = ref(1)
const total = ref(0)
let epoch = 0
async function load(next = 1) {
  const current = ++epoch
  loading.value = true
  error.value = ''
  try {
    const response = await api.billingRecordDetails(props.recordId, { novel_id: props.novelId, page: next, page_size: 20 })
    if (current !== epoch) return
    records.value = response.data.items
    page.value = response.data.pagination.page
    pages.value = response.data.pagination.pages
    total.value = response.data.pagination.total
  } catch (reason) {
    if (current === epoch) error.value = reason instanceof Error ? reason.message : '费用明细加载失败'
  } finally {
    if (current === epoch) loading.value = false
  }
}
watch(() => [props.recordId, props.novelId], () => { records.value = []; void load() }, { immediate: true })
onBeforeUnmount(() => { epoch += 1 })
</script>

<template>
  <section class="billing-record-details" aria-label="会话费用明细" :aria-busy="loading">
    <p>按原始计费记录核对，包含各轮模型调用与摘要消耗。</p>
    <p v-if="loading" role="status">正在读取明细…</p>
    <p v-else-if="error" role="alert">{{ error }} <AppButton size="xs" @click="load(page)">重试</AppButton></p>
    <template v-else>
      <table><thead><tr><th>时间</th><th>模型 / 用量</th><th>状态</th><th v-if="showSource">来源</th><th class="is-num">成本</th></tr></thead>
        <tbody><tr v-for="record in records" :key="record.id">
          <td>{{ record.created_at }}</td><td>{{ record.model_name || record.model }}<small>{{ usageLabel(record) }}</small></td>
          <td>{{ recordStatus(record) }}</td><td v-if="showSource">{{ costSourceLabel(record.cost_source) }}</td>
          <td class="is-num">{{ money(record.cost, record.currency) }}</td>
        </tr></tbody>
      </table>
      <footer><span>共 {{ total }} 条原始记录</span><div v-if="pages > 1">
        <AppButton size="xs" :disabled="page <= 1" @click="load(page - 1)">上一页明细</AppButton>
        <span>{{ page }} / {{ pages }}</span><AppButton size="xs" :disabled="page >= pages" @click="load(page + 1)">下一页明细</AppButton>
      </div></footer>
    </template>
  </section>
</template>

<style scoped>
.billing-record-details { padding: 12px 20px; color: var(--app-text-secondary); background: var(--app-surface-muted); }
p { margin: 0 0 10px; font-size: 11px; }
table { width: 100%; border-collapse: collapse; font-size: 11px; }
th, td { padding: 7px 10px; text-align: left; border-bottom: 1px solid var(--app-border); }
th { color: var(--app-text-muted); font-weight: 500; }small { display: block; margin-top: 3px; color: var(--app-text-muted); }
.is-num { text-align: right; font-variant-numeric: tabular-nums; } footer, footer > div { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
footer { margin-top: 8px; font-size: 11px; }
</style>
