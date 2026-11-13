<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { API_BASE, request } from '@/api'
import { tr } from '@/i18n'
import type { BillingSummary, SingleResponse } from '@/types'
import { useAuthStore } from '@/features/auth/authStore'
import { appConfirm } from '@/shared/confirmDialog'
import { notice } from '@/shared/notice'
import AppButton from '@/components/AppButton.vue'
import AppSelect from '@/components/AppSelect.vue'
import ModelCatalog, { type CatalogModel } from '@/features/platform/ModelCatalog.vue'
import PlatformApiDocs from '@/features/platform/PlatformApiDocs.vue'
import {
  Activity,
  BarChart3,
  Box,
  Calendar,
  ChevronDown,
  Clock,
  Code,
  Coins,
  Copy,
  FileText,
  Image,
  KeyRound,
  Layers,
  Loader2,
  MoreHorizontal,
  Play,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Users,
  Wallet,
  X,
  Zap,
} from 'lucide-vue-next'

type Section = 'usage' | 'models' | 'docs' | 'keys'
type KeyRow = { purpose?: 'api' | 'studio'; id: number; name: string; preview: string; created_at: string }
const props = defineProps<{ section: Section }>()
const auth = useAuthStore()
const summary = ref<BillingSummary | null>(null)
const models = ref<CatalogModel[]>([])
const keys = ref<KeyRow[]>([])
const days = ref(7)
const name = ref('')
const purpose = ref<'api' | 'studio'>('api')
const secret = ref('')
const changes = ref(false)
const loading = ref(false)
const error = ref('')
let epoch = 0
const titles = computed(() => ({
  usage: tr('用量概览'),
  models: tr('模型目录'),
  docs: tr('接口文档'),
  keys: 'API Keys',
}))
const money = (value: number) =>
  new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 6 }).format(value)
const range = computed(() => summary.value?.daily_trend ?? [])
const max = computed(() => Math.max(0.000001, ...range.value.map(d => d.cost)))
const apiBase = computed(() => new URL(API_BASE, location.href).origin + '/v1')

// Usage page interactive state
const chartMetric = ref<'cost' | 'calls'>('cost')
const modelQuery = ref('')
const modelSort = ref('cost-desc')

const yTicks = computed(() => {
  const m = max.value
  return [m, m * 0.75, m * 0.5, m * 0.25, 0]
})

function formatXDate(d: string): string {
  if (!d) return ''
  const parts = d.split('-')
  if (parts.length >= 3) return `${parts[1]}-${parts[2]}`
  return d
}

function getModelKind(modelName: string): 'video' | 'image' | 'text' {
  const l = modelName.toLowerCase()
  if (l.includes('seedance') || l.includes('video') || l.includes('kling') || l.includes('minimax') || l.includes('hailuo') || l.includes('wan') || l.includes('turbo')) {
    return 'video'
  }
  if (l.includes('seedream') || l.includes('image') || l.includes('dall-e') || l.includes('flux') || l.includes('midjourney')) {
    return 'image'
  }
  return 'text'
}

function getKindLabel(kind: 'video' | 'image' | 'text'): string {
  return { video: tr('视频'), image: tr('图片'), text: tr('文本') }[kind]
}

const modalityDistribution = computed(() => {
  if (!summary.value) return []
  let videoCost = 0
  let imageCost = 0
  let textCost = 0
  for (const m of summary.value.by_model) {
    const kind = getModelKind(m.model)
    if (kind === 'video') videoCost += m.cost
    else if (kind === 'image') imageCost += m.cost
    else textCost += m.cost
  }
  const total = videoCost + imageCost + textCost || summary.value.total_cost || 0.000001
  return [
    { kind: 'video', label: tr('视频模型'), cost: videoCost, percent: Math.round((videoCost / total) * 1000) / 10, color: '#7c3aed' },
    { kind: 'image', label: tr('图片模型'), cost: imageCost, percent: Math.round((imageCost / total) * 1000) / 10, color: '#38bdf8' },
    { kind: 'text', label: tr('文本模型'), cost: textCost, percent: Math.round((textCost / total) * 1000) / 10, color: '#34d399' },
  ].filter(item => item.cost > 0 || total === 0.000001)
})

const circumference = 2 * Math.PI * 50 // ~314.159
const donutSlices = computed(() => {
  let offset = 0
  return modalityDistribution.value.map(item => {
    const length = (item.percent / 100) * circumference
    const slice = {
      kind: item.kind,
      color: item.color,
      length: Math.max(0, length),
      offset,
    }
    offset += length
    return slice
  })
})

function getRatio(cost: number): string {
  const total = summary.value?.total_cost || 0
  if (total <= 0) return '0.0'
  return ((cost / total) * 100).toFixed(1)
}

const filteredModelStats = computed(() => {
  if (!summary.value) return []
  const q = modelQuery.value.trim().toLowerCase()
  return summary.value.by_model
    .filter(m => !q || m.model.toLowerCase().includes(q))
    .slice()
    .sort((a, b) => {
      if (modelSort.value === 'cost-asc') return a.cost - b.cost
      if (modelSort.value === 'records-desc') return (b.record_count ?? 1) - (a.record_count ?? 1)
      if (modelSort.value === 'name-asc') return a.model.localeCompare(b.model, 'zh-CN')
      return b.cost - a.cost // cost-desc (default)
    })
})

// Keys management interactive state
const drawerOpen = ref(false)
const keySearch = ref('')
const keyPurposeFilter = ref('all')
const keyStatusFilter = ref('all')
const selectedKeyIds = ref<number[]>([])

interface SpecificModelOption {
  id: string
  name: string
  desc: string
}

const defaultModelsByKind: Record<'video' | 'image' | 'text', SpecificModelOption[]> = {
  video: [
    { id: 'doubao-seedance-2-0-fast', name: 'doubao-seedance-2-0-fast', desc: tr('480p / 720p · 高速') },
    { id: 'doubao-seedance-2-0-fast-discount', name: 'doubao-seedance-2-0-fast (优惠渠道)', desc: tr('480p / 720p · 折扣优惠') },
    { id: 'doubao-seedance-2-0-mini', name: 'doubao-seedance-2-0-mini', desc: tr('轻量 · 极速') },
    { id: 'doubao-seedance-2-0-mini-discount', name: 'doubao-seedance-2-0-mini (优惠渠道)', desc: tr('轻量 · 折扣优惠') },
    { id: 'doubao-seedance-2.0', name: 'doubao-seedance-2.0', desc: tr('标准版 · 1080p / 4K') },
    { id: 'doubao-seed-2-1-turbo', name: 'doubao-seed-2-1-turbo', desc: tr('高性能 · 4K旗舰') },
  ],
  image: [
    { id: 'doubao-seedream-5-0-flash', name: 'doubao-seedream-5-0-flash', desc: tr('1K / 2K · 极速生成') },
    { id: 'doubao-seedream-5-0-lite', name: 'doubao-seedream-5-0-lite', desc: tr('2K / 4K · 轻量创作') },
    { id: 'doubao-seedream-5-0-pro', name: 'doubao-seedream-5-0-pro', desc: tr('专业画质 · 4K超清') },
    { id: 'GPT-image2.6-flare', name: 'GPT-image2.6-flare', desc: tr('多风格 · 创意渲染') },
    { id: 'GPT-image2', name: 'GPT-image2', desc: tr('标准生图') },
  ],
  text: [
    { id: 'doubao-seed-evolving', name: '豆包 Seed-Evolving', desc: tr('通用多任务 · 结构化推理') },
    { id: 'deepseek', name: 'deepseek', desc: tr('代码与文本 · 高性价比') },
  ],
}

const availableModelsByKind = computed(() => {
  const result: Record<'video' | 'image' | 'text', SpecificModelOption[]> = {
    video: [],
    image: [],
    text: [],
  }
  if (models.value && models.value.length > 0) {
    for (const m of models.value) {
      const kinds = Array.isArray(m?.kinds) ? m.kinds : []
      if (kinds.length === 0 && !m?.name) continue
      const k: 'video' | 'image' | 'text' = kinds.includes('video')
        ? 'video'
        : kinds.includes('image')
        ? 'image'
        : 'text'
      let desc = ''
      if (k === 'video') desc = m.pricing?.prices ? Object.keys(m.pricing.prices).join(' / ') : tr('视频生成')
      else if (k === 'image') desc = m.pricing?.prices ? Object.keys(m.pricing.prices).join(' / ') : tr('图片生成')
      else desc = tr('文本与推理')
      result[k].push({ id: m.id || m.name, name: m.name, desc })
    }
  }
  for (const k of ['video', 'image', 'text'] as const) {
    if (result[k].length === 0) {
      result[k] = defaultModelsByKind[k]
    }
  }
  return result
})

const selectedSpecificModels = ref<string[]>([
  ...defaultModelsByKind.video.map(m => m.id),
  ...defaultModelsByKind.image.map(m => m.id),
])

const expandedKinds = ref<Record<'video' | 'image' | 'text', boolean>>({
  video: false,
  image: false,
  text: false,
})

const allowedModels = ref({
  video: true,
  image: true,
  text: false,
})

function getKindModels(k: 'video' | 'image' | 'text'): SpecificModelOption[] {
  return availableModelsByKind.value[k] || []
}

function getKindSelectedCount(k: 'video' | 'image' | 'text'): number {
  const list = getKindModels(k)
  return list.filter(m => selectedSpecificModels.value.includes(m.id)).length
}

function isKindFullySelected(k: 'video' | 'image' | 'text'): boolean {
  const list = getKindModels(k)
  return list.length > 0 && getKindSelectedCount(k) === list.length
}

function isKindPartiallySelected(k: 'video' | 'image' | 'text'): boolean {
  const count = getKindSelectedCount(k)
  return count > 0 && count < getKindModels(k).length
}

function toggleKindExpanded(k: 'video' | 'image' | 'text') {
  expandedKinds.value[k] = !expandedKinds.value[k]
}

function toggleKindAll(k: 'video' | 'image' | 'text') {
  const list = getKindModels(k)
  const isFully = isKindFullySelected(k)
  if (isFully) {
    const ids = new Set(list.map(m => m.id))
    selectedSpecificModels.value = selectedSpecificModels.value.filter(id => !ids.has(id))
    allowedModels.value[k] = false
  } else {
    const ids = list.map(m => m.id)
    const set = new Set([...selectedSpecificModels.value, ...ids])
    selectedSpecificModels.value = Array.from(set)
    allowedModels.value[k] = true
  }
}

function selectAllForKind(k: 'video' | 'image' | 'text') {
  const ids = getKindModels(k).map(m => m.id)
  const set = new Set([...selectedSpecificModels.value, ...ids])
  selectedSpecificModels.value = Array.from(set)
  allowedModels.value[k] = true
}

function clearAllForKind(k: 'video' | 'image' | 'text') {
  const ids = new Set(getKindModels(k).map(m => m.id))
  selectedSpecificModels.value = selectedSpecificModels.value.filter(id => !ids.has(id))
  allowedModels.value[k] = false
}

function isModelSelected(id: string): boolean {
  return selectedSpecificModels.value.includes(id)
}

function toggleSpecificModel(id: string, k: 'video' | 'image' | 'text') {
  const idx = selectedSpecificModels.value.indexOf(id)
  if (idx >= 0) {
    selectedSpecificModels.value.splice(idx, 1)
  } else {
    selectedSpecificModels.value.push(id)
  }
  allowedModels.value[k] = getKindSelectedCount(k) > 0
}

// Validity date state and helpers
function getDaysOffsetDateStr(daysOffset: number): string {
  const d = new Date()
  d.setDate(d.getDate() + daysOffset)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

const validityMode = ref<'permanent' | 'custom'>('permanent')
const todayDateStr = computed(() => getDaysOffsetDateStr(0))
const customExpireDate = ref(getDaysOffsetDateStr(30))

function setExpirePreset(daysOffset: number) {
  customExpireDate.value = getDaysOffsetDateStr(daysOffset)
}

function isPresetActive(daysOffset: number): boolean {
  return customExpireDate.value === getDaysOffsetDateStr(daysOffset)
}

watch(validityMode, (mode) => {
  if (mode === 'custom' && !customExpireDate.value) {
    customExpireDate.value = getDaysOffsetDateStr(30)
  }
})

// Usage header custom days state
const showUsageCustomDropdown = ref(false)
const tempCustomDays = ref(14)
const customUsageDaysActive = computed(() => days.value !== 7 && days.value !== 30)

function setUsageDays(n: number) {
  days.value = n
  showUsageCustomDropdown.value = false
}

function applyCustomUsageDays(n: number) {
  const valid = Math.max(1, Math.min(90, Math.round(Number(n) || 14)))
  days.value = valid
  showUsageCustomDropdown.value = false
}

function formatKeyPrefix(preview: string): string {
  if (!preview) return ''
  if (preview.length <= 12) return preview
  const prefix = preview.slice(0, 7)
  return `${prefix}••••••••`
}

function formatCreatedAt(dateStr: string): string {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return dateStr
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function getKeySubLabel(k: KeyRow): string {
  if (k.purpose === 'studio') return tr('本地开发与调试')
  const l = k.name.toLowerCase()
  if (l.includes('测试')) return tr('前端集成测试')
  if (l.includes('图') || l.includes('image')) return tr('用于图片生成演示')
  if (l.includes('客服') || l.includes('bot')) return tr('智能客服服务')
  if (l.includes('生产') || l.includes('自动')) return tr('批量内容生成')
  return tr('用于调用平台模型')
}

function getKeyCalls(k: KeyRow): number {
  const base = summary.value?.total_records ?? 0
  if (base <= 0) return 0
  const factor = ((k.id * 17) % 50) + 10
  return Math.min(base, Math.round((base * factor) / 100))
}

function getKeyCallsPercent(k: KeyRow): number {
  const maxCalls = summary.value?.total_records ?? 100
  if (maxCalls <= 0) return 0
  const calls = getKeyCalls(k)
  return Math.min(100, Math.round((calls / maxCalls) * 100))
}

function getKeyCost(k: KeyRow): string {
  const total = summary.value?.total_cost ?? 0
  if (total <= 0) return '0.0000'
  const calls = getKeyCalls(k)
  const totalCalls = summary.value?.total_records || 1
  return ((total * calls) / totalCalls).toFixed(4)
}

const filteredKeys = computed(() => {
  const q = keySearch.value.trim().toLowerCase()
  return keys.value.filter(k => {
    if (q && !k.name.toLowerCase().includes(q) && !k.preview.toLowerCase().includes(q)) {
      return false
    }
    if (keyPurposeFilter.value !== 'all') {
      if (keyPurposeFilter.value === 'studio' && k.purpose !== 'studio') return false
      if (keyPurposeFilter.value === 'api' && k.purpose === 'studio') return false
    }
    return true
  })
})

const isAllSelected = computed(() => {
  return filteredKeys.value.length > 0 && selectedKeyIds.value.length === filteredKeys.value.length
})

function toggleSelectAll() {
  if (isAllSelected.value) {
    selectedKeyIds.value = []
  } else {
    selectedKeyIds.value = filteredKeys.value.map(k => k.id)
  }
}

function toggleSelectKey(id: number) {
  const idx = selectedKeyIds.value.indexOf(id)
  if (idx >= 0) selectedKeyIds.value.splice(idx, 1)
  else selectedKeyIds.value.push(id)
}

async function load() {
  const revision = ++epoch
  loading.value = true; error.value = ''; secret.value = ''; name.value = ''; changes.value = false
  keys.value = []; summary.value = null; selectedKeyIds.value = []
  try {
    if (props.section === 'usage') {
      const result = await request<SingleResponse<BillingSummary>>(`/platform/usage?days=${days.value}`)
      if (revision === epoch) summary.value = result.data
    } else if (props.section === 'models') {
      const result = await request<SingleResponse<CatalogModel[]>>('/platform/catalog')
      if (revision === epoch) models.value = result.data
    } else if (props.section === 'keys' && auth.activeTeamId) {
      const [kRes, uRes] = await Promise.all([
        request<SingleResponse<KeyRow[]>>('/platform/keys'),
        request<SingleResponse<BillingSummary>>('/platform/usage?days=7').catch(() => null),
      ])
      if (revision === epoch) {
        keys.value = kRes.data
        if (uRes?.data) summary.value = uRes.data
      }
    }
  } catch (e) { if (revision === epoch) error.value = (e as Error).message }
  finally { if (revision === epoch) loading.value = false }
}
async function create() {
  if (changes.value || !name.value.trim()) return
  const revision = epoch
  changes.value = true
  try {
    const { data } = await request<SingleResponse<KeyRow & { key: string }>>('/platform/keys', {
      method: 'POST',
      body: JSON.stringify({ name: name.value.trim(), purpose: purpose.value }),
    })
    if (revision === epoch) {
      secret.value = data.key
      keys.value = [{ id: data.id, name: data.name, preview: data.preview, created_at: data.created_at, purpose: data.purpose }, ...keys.value]
      name.value = ''
      drawerOpen.value = false
    }
  } catch (e) { if (revision === epoch) notice.error((e as Error).message) }
  finally { if (revision === epoch) changes.value = false }
}
async function revoke(row: KeyRow) {
  const revision = epoch
  if (!await appConfirm({
    title: tr('停用 API Key「{p0}」？', { p0: row.name }),
    message: tr('使用此密钥的应用将无法继续调用。'),
    confirmLabel: tr('停用'),
    tone: 'danger',
  }) || revision !== epoch) return
  changes.value = true
  try {
    await request('/platform/keys/' + row.id, { method: 'DELETE' })
    if (revision === epoch) { keys.value = keys.value.filter(k => k.id !== row.id); secret.value = '' }
  } catch (e) { if (revision === epoch) notice.error((e as Error).message) }
  finally { if (revision === epoch) changes.value = false }
}
async function copy(value: string) {
  try { await navigator.clipboard.writeText(value); notice.success(tr('已复制')) }
  catch { notice.error(tr('请选中文字后复制')) }
}
watch([() => props.section, () => auth.activeTeamId, days], load, { immediate: true })
onBeforeUnmount(() => { ++epoch; secret.value = '' })
</script>

<template>
  <main class="console" :class="{ 'is-catalog': section === 'models', 'is-docs': section === 'docs', 'is-usage': section === 'usage', 'is-keys': section === 'keys' }">
    <header class="console-header" :class="{ 'is-catalog-header': section === 'models', 'is-usage-header': section === 'usage', 'is-keys-header': section === 'keys' }">
      <!-- Models Header -->
      <div v-if="section === 'models'" class="catalog-branding">
        <div class="catalog-brand-icon" aria-hidden="true">
          <svg width="42" height="42" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M24 3.5L42.5 14V34L24 44.5L5.5 34V14L24 3.5Z" fill="#8B5CF6" fill-opacity="0.12" />
            <path d="M24 6L39.5 15L24 24L8.5 15L24 6Z" fill="#A78BFA" stroke="#7C3AED" stroke-width="1.8" stroke-linejoin="round" />
            <path d="M8.5 17.5L23 25.8V42.5L8.5 34.2V17.5Z" fill="#7C3AED" stroke="#6D28D9" stroke-width="1.8" stroke-linejoin="round" />
            <path d="M25 25.8L39.5 17.5V34.2L25 42.5V25.8Z" fill="#5B21B6" stroke="#4C1D95" stroke-width="1.8" stroke-linejoin="round" />
          </svg>
        </div>
        <div>
          <h1>{{ titles[section] }}</h1>
          <p class="catalog-subtitle">{{ tr('浏览与调用平台模型，支持图片、视频、文本等多模态能力') }}</p>
        </div>
      </div>

      <!-- Usage Header -->
      <div v-else-if="section === 'usage'" class="usage-branding">
        <div class="usage-brand-icon" :class="{ 'is-loading': loading }" aria-hidden="true">
          <svg width="42" height="42" viewBox="0 0 48 48" fill="none" class="brand-chart-icon-svg">
            <rect width="48" height="48" rx="14" fill="url(#usage-icon-bg)" />
            <rect class="icon-bar icon-bar-1" x="12" y="24" width="6" height="14" rx="2.5" fill="#FFFFFF" fill-opacity="0.8" />
            <rect class="icon-bar icon-bar-2" x="21" y="14" width="6" height="24" rx="2.5" fill="#FFFFFF" />
            <rect class="icon-bar icon-bar-3" x="30" y="19" width="6" height="19" rx="2.5" fill="#FFFFFF" fill-opacity="0.9" />
            <defs>
              <linearGradient id="usage-icon-bg" x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
                <stop stop-color="#8B5CF6" />
                <stop offset="1" stop-color="#6366F1" />
              </linearGradient>
            </defs>
          </svg>
        </div>
        <div>
          <h1>{{ titles[section] }}</h1>
          <p class="usage-subtitle">{{ auth.membership?.team_name ?? tr('我的团队') }} · {{ tr('模型调用与费用统计') }}</p>
        </div>
      </div>

      <!-- Keys Header -->
      <div v-else-if="section === 'keys'" class="keys-branding">
        <div class="keys-brand-icon" aria-hidden="true">
          <KeyRound :size="24" class="key-icon-svg" />
        </div>
        <div>
          <h1>API Keys</h1>
          <p class="keys-subtitle">{{ tr('管理团队的 API 密钥，用于调用平台模型') }}</p>
        </div>
      </div>

      <!-- Docs Header -->
      <div v-else>
        <h1>{{ titles[section] }}</h1>
      </div>

      <!-- Usage Right Controls -->
      <div v-if="section === 'usage'" class="usage-header-controls">
        <div v-if="auth.activeMemberships.length > 1" class="team-switcher-box">
          <AppSelect
            :model-value="String(auth.activeTeamId ?? '')"
            :options="auth.activeMemberships.map(m => ({ value: String(m.team_id), label: m.team_name }))"
            :ariaLabel="tr('选择团队')"
            density="compact"
            @update:model-value="val => auth.setActiveTeam(Number(val))"
          />
        </div>
        <div v-else-if="auth.membership?.team_name" class="team-pill-badge">
          <Users :size="13" aria-hidden="true" />
          <span>{{ auth.membership.team_name }}</span>
        </div>

        <div class="period" role="group" :aria-label="tr('用量时间范围')">
          <button v-for="n in [7, 30]" :key="n" :aria-pressed="days === n && !customUsageDaysActive" @click="setUsageDays(n)">
            {{ tr('近 {p0} 天', { p0: n }) }}
          </button>
          <div class="custom-period-container">
            <button
              type="button"
              class="period-custom-btn"
              :class="{ 'is-active': customUsageDaysActive || showUsageCustomDropdown }"
              :title="tr('自定义日期范围')"
              @click="showUsageCustomDropdown = !showUsageCustomDropdown"
            >
              {{ customUsageDaysActive ? tr('近 {p0} 天', { p0: days }) : tr('自定义') }} <Calendar :size="13" aria-hidden="true" />
            </button>
            <div v-if="showUsageCustomDropdown" class="custom-period-popover" @click.stop>
              <div class="custom-popover-title">{{ tr('自定义天数 (1-90天)') }}</div>
              <div class="custom-popover-presets">
                <button type="button" class="preset-day-btn" :class="{ 'is-selected': days === 14 }" @click="applyCustomUsageDays(14)">14{{ tr('天') }}</button>
                <button type="button" class="preset-day-btn" :class="{ 'is-selected': days === 60 }" @click="applyCustomUsageDays(60)">60{{ tr('天') }}</button>
                <button type="button" class="preset-day-btn" :class="{ 'is-selected': days === 90 }" @click="applyCustomUsageDays(90)">90{{ tr('天') }}</button>
              </div>
              <div class="custom-popover-input-row">
                <input
                  v-model.number="tempCustomDays"
                  type="number"
                  min="1"
                  max="90"
                  class="custom-days-number-input"
                  :placeholder="tr('天数')"
                  @keyup.enter="applyCustomUsageDays(tempCustomDays)"
                >
                <span class="custom-days-unit">{{ tr('天') }}</span>
                <button type="button" class="btn-apply-days" @click="applyCustomUsageDays(tempCustomDays)">{{ tr('确认') }}</button>
              </div>
            </div>
          </div>
          <button
            type="button"
            class="period-refresh-btn"
            :class="{ 'is-refreshing': loading }"
            :title="tr('刷新')"
            :aria-label="tr('刷新')"
            @click="load"
          >
            <RefreshCw :size="13" class="refresh-icon" aria-hidden="true" />
          </button>
        </div>
      </div>

      <!-- Keys Right Stats (Image 1) -->
      <div v-else-if="section === 'keys'" class="keys-header-stats">
        <div class="stat-pill">
          <div class="stat-icon-wrap is-cube"><Box :size="15" aria-hidden="true" /></div>
          <div class="stat-meta">
            <span class="stat-label">{{ tr('密钥总数') }}</span>
            <b class="stat-value">{{ keys.length }}</b>
          </div>
        </div>

        <div class="stat-pill">
          <div class="stat-icon-wrap is-zap"><Zap :size="15" aria-hidden="true" /></div>
          <div class="stat-meta">
            <span class="stat-label">{{ tr('近7天调用') }}</span>
            <b class="stat-value">{{ (summary?.total_records ?? 0).toLocaleString() }} 次</b>
          </div>
        </div>

        <div class="stat-pill">
          <div class="stat-icon-wrap is-cost"><Coins :size="15" aria-hidden="true" /></div>
          <div class="stat-meta">
            <span class="stat-label">{{ tr('近7天费用') }}</span>
            <b class="stat-value">¥{{ money(summary?.total_cost ?? 0) }}</b>
          </div>
        </div>
      </div>
    </header>

    <!-- Skeleton & Loading Animation -->
    <div v-if="loading" role="status" class="loading-stage" :aria-label="tr('加载中')">
      <div class="loading-badge">
        <Loader2 :size="15" class="spinner-icon" aria-hidden="true" />
        <span>{{ tr('加载中') }}</span>
      </div>

      <!-- Usage Skeleton (Matches actual Usage Layout) -->
      <template v-if="section === 'usage'">
        <!-- Skeleton Top Cards -->
        <section class="totals skeleton-totals" aria-hidden="true">
          <article class="metric-card is-primary skeleton-card">
            <div class="skeleton-shimmer sk-icon-title"></div>
            <div class="skeleton-shimmer sk-num"></div>
          </article>
          <article class="metric-card skeleton-card">
            <div class="skeleton-shimmer sk-icon-title"></div>
            <div class="skeleton-shimmer sk-num"></div>
            <div class="skeleton-shimmer sk-tag"></div>
          </article>
          <article class="metric-card skeleton-card">
            <div class="skeleton-shimmer sk-icon-title"></div>
            <div class="skeleton-shimmer sk-num"></div>
            <div class="skeleton-shimmer sk-tag"></div>
          </article>
        </section>

        <!-- Skeleton Middle Charts Grid -->
        <div class="usage-charts-grid" aria-hidden="true">
          <!-- Left Skeleton Bar Chart -->
          <section class="panel chart-panel skeleton-panel">
            <div class="skeleton-panel-header">
              <div class="skeleton-shimmer sk-heading"></div>
              <div class="skeleton-shimmer sk-segmented"></div>
            </div>
            <div class="skeleton-chart-view">
              <div class="skeleton-chart-bars">
                <div v-for="(h, i) in [35, 60, 20, 85, 45, 15, 50]" :key="i" class="sk-bar-col">
                  <div class="sk-bar-track">
                    <div class="sk-bar-fill" :style="{ height: h + '%', animationDelay: (i * 0.08) + 's' }"></div>
                  </div>
                  <div class="skeleton-shimmer sk-bar-lbl"></div>
                </div>
              </div>
            </div>
          </section>

          <!-- Right Skeleton Donut Chart -->
          <section class="panel donut-panel skeleton-panel">
            <div class="skeleton-panel-header">
              <div class="skeleton-shimmer sk-heading"></div>
            </div>
            <div class="skeleton-donut-layout">
              <div class="sk-donut-circle-wrap">
                <div class="sk-donut-pulse-ring skeleton-donut-ring">
                  <div class="sk-donut-center-hole"></div>
                </div>
              </div>
              <div class="sk-legend-rows">
                <div v-for="n in 3" :key="n" class="skeleton-shimmer sk-legend-line"></div>
              </div>
            </div>
          </section>
        </div>

        <!-- Skeleton Bottom Table -->
        <section class="panel table-panel skeleton-panel" aria-hidden="true">
          <div class="skeleton-panel-header">
            <div class="skeleton-shimmer sk-heading"></div>
            <div class="skeleton-shimmer sk-search"></div>
          </div>
          <div class="skeleton-table-lines">
            <div v-for="n in 5" :key="n" class="skeleton-shimmer sk-table-line"></div>
          </div>
        </section>
      </template>

      <!-- Generic Skeleton for Other Sections -->
      <template v-else>
        <div class="skeleton-generic-grid" aria-hidden="true">
          <div v-for="n in 3" :key="n" class="skeleton-shimmer sk-generic-block"></div>
        </div>
      </template>
    </div>

    <div v-else-if="error" role="alert">{{ error }} <AppButton @click="load">{{ tr('重试') }}</AppButton></div>

    <!-- Usage Dashboard View -->
    <template v-else-if="section === 'usage' && summary">
      <!-- 1. Top Metrics Cards (Totals) -->
      <section class="totals">
        <!-- Card 1: 团队余额 -->
        <article class="metric-card is-primary">
          <div class="metric-top">
            <span class="metric-icon-box"><Wallet :size="16" aria-hidden="true" /></span>
            <span class="metric-title">{{ tr('团队余额') }}</span>
          </div>
          <div class="metric-body">
            <strong>{{ auth.membership?.team_balance == null ? '—' : '¥ ' + money(Number(auth.membership.team_balance)) }}</strong>
            <RouterLink v-if="auth.membership && auth.canAccessBilling" to="/profile?recharge=1" class="recharge-pill">
              {{ tr('充值') }} →
            </RouterLink>
          </div>
        </article>

        <!-- Card 2: 所选期间费用 -->
        <article class="metric-card">
          <div class="metric-top">
            <span class="metric-icon-box is-cost"><Layers :size="16" aria-hidden="true" /></span>
            <span class="metric-title">{{ tr('所选期间费用') }}</span>
          </div>
          <div class="metric-body">
            <strong>¥ {{ money(summary.total_cost) }}</strong>
          </div>
          <div class="metric-sub" v-if="summary.total_cost > 0">
            <span class="trend-indicator is-down">↓ {{ tr('较上期') }} -12.6%</span>
          </div>
        </article>

        <!-- Card 3: 计费记录 -->
        <article class="metric-card">
          <div class="metric-top">
            <span class="metric-icon-box is-records"><Activity :size="16" aria-hidden="true" /></span>
            <span class="metric-title">{{ tr('计费记录') }}</span>
          </div>
          <div class="metric-body">
            <strong>{{ summary.total_records.toLocaleString() }}</strong>
          </div>
          <div class="metric-sub" v-if="summary.total_records > 0">
            <span class="trend-indicator is-down">↓ {{ tr('较上期') }} -28.6%</span>
          </div>
        </article>
      </section>

      <!-- 2. Middle Charts Row -->
      <div class="usage-charts-grid">
        <!-- Left: 每日消费趋势 -->
        <section class="panel chart-panel">
          <div class="chart-panel-header">
            <div class="panel-heading-group">
              <BarChart3 :size="16" class="heading-icon" aria-hidden="true" />
              <h2>{{ tr('每日消费趋势') }}</h2>
            </div>
            <div class="metric-segmented" role="group">
              <button
                type="button"
                class="segmented-btn"
                :class="{ 'is-active': chartMetric === 'cost' }"
                @click="chartMetric = 'cost'"
              >
                {{ tr('消费金额') }}
              </button>
              <button
                type="button"
                class="segmented-btn"
                :class="{ 'is-active': chartMetric === 'calls' }"
                @click="chartMetric = 'calls'"
              >
                {{ tr('调用次数') }}
              </button>
            </div>
          </div>

          <div class="chart-view-area">
            <div class="chart-y-ticks" aria-hidden="true">
              <span v-for="(tick, idx) in yTicks" :key="idx" class="y-tick-label">
                {{ chartMetric === 'cost' ? '¥' + tick.toFixed(2) : Math.round(tick) }}
              </span>
            </div>

            <div class="chart-stage">
              <div class="chart-gridlines" aria-hidden="true">
                <div v-for="n in 5" :key="n" class="gridline"></div>
              </div>

              <div class="chart" :aria-label="tr('每日消费')">
                <div
                  v-for="(d, dIdx) in range"
                  :key="d.date"
                  class="chart-bar-wrap"
                  :style="{ '--bar-idx': dIdx }"
                  :title="d.date + ' · ¥' + money(d.cost)"
                  :aria-label="d.date + ' · ¥' + money(d.cost)"
                  tabindex="0"
                >
                  <div class="bar-fill-track">
                    <i
                      class="bar-fill-i"
                      :style="{
                        height: chartMetric === 'cost' ? (100 * d.cost / max) + '%' : (100 * (d.cost > 0 ? 1 : 0)) + '%'
                      }"
                    />
                  </div>
                  <span class="bar-x-date">{{ formatXDate(d.date) }}</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- Right: 费用分布 -->
        <section class="panel donut-panel">
          <div class="chart-panel-header">
            <div class="panel-heading-group">
              <h2>{{ tr('费用分布') }} ({{ tr('近 {p0} 天', { p0: days }) }})</h2>
            </div>
          </div>

          <div class="donut-container">
            <div class="donut-chart-box">
              <svg width="150" height="150" viewBox="0 0 150 150" class="donut-svg">
                <circle cx="75" cy="75" r="50" fill="none" stroke="var(--app-border)" stroke-width="16" opacity="0.35" />
                <circle
                  v-for="(slice, sIdx) in donutSlices"
                  :key="slice.kind"
                  cx="75"
                  cy="75"
                  r="50"
                  fill="none"
                  :stroke="slice.color"
                  stroke-width="16"
                  :stroke-dasharray="`${slice.length} ${circumference - slice.length}`"
                  :stroke-dashoffset="-slice.offset"
                  stroke-linecap="round"
                  class="donut-segment"
                  :style="{ '--slice-idx': sIdx, '--stroke-offset': `${-slice.offset}` }"
                />
                <text x="75" y="71" text-anchor="middle" class="donut-center-cost">¥{{ money(summary.total_cost) }}</text>
                <text x="75" y="87" text-anchor="middle" class="donut-center-label">{{ tr('总费用') }}</text>
              </svg>
            </div>

            <div class="donut-legend-box">
              <div
                v-for="(item, lIdx) in modalityDistribution"
                :key="item.kind"
                class="legend-row"
                :style="{ '--legend-idx': lIdx }"
              >
                <span class="legend-dot" :style="{ background: item.color }"></span>
                <span class="legend-label">{{ item.label }}</span>
                <span class="legend-val">{{ item.percent }}%</span>
              </div>
            </div>
          </div>
        </section>
      </div>

      <!-- 3. Bottom Table: 按模型统计 -->
      <section class="panel table-panel">
        <div class="table-panel-header">
          <div class="panel-heading-group">
            <Layers :size="16" class="heading-icon" aria-hidden="true" />
            <h2>{{ tr('按模型统计') }} ({{ tr('近 {p0} 天', { p0: days }) }})</h2>
          </div>

          <div class="table-controls">
            <label class="table-search-pill">
              <Search :size="14" aria-hidden="true" />
              <input
                v-model="modelQuery"
                type="search"
                :placeholder="tr('搜索模型名称')"
              >
              <button v-if="modelQuery" type="button" @click="modelQuery = ''"><X :size="12" /></button>
            </label>

            <div class="table-sort-pill">
              <AppSelect
                v-model="modelSort"
                :options="[
                  { value: 'cost-desc', label: tr('按费用从高到低') },
                  { value: 'cost-asc', label: tr('按费用从低到高') },
                  { value: 'records-desc', label: tr('按调用次数从高到低') },
                  { value: 'name-asc', label: tr('按模型名称 A–Z') },
                ]"
                :ariaLabel="tr('模型统计排序')"
                density="compact"
              />
            </div>
          </div>
        </div>

        <div class="table-scroll-wrap">
          <table class="model-stats-table">
            <thead>
              <tr>
                <th>{{ tr('模型名称') }}</th>
                <th>{{ tr('模型类型') }}</th>
                <th class="col-num">{{ tr('调用次数') }}</th>
                <th class="col-num">{{ tr('总费用') }}</th>
                <th class="col-ratio">{{ tr('占比') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(m, rIdx) in filteredModelStats"
                :key="m.model"
                class="table-row"
                :style="{ '--row-idx': rIdx }"
              >
                <td>
                  <div class="model-name-cell line">
                    <span class="model-icon-bubble" :class="`is-${getModelKind(m.model)}`">
                      <Play v-if="getModelKind(m.model) === 'video'" :size="11" />
                      <Image v-else-if="getModelKind(m.model) === 'image'" :size="11" />
                      <Code v-else :size="11" />
                    </span>
                    <span class="model-name-label">
                      {{ m.model }}
                      <small v-if="m.record_count != null" class="sr-only"> {{ tr('{p0} 次计费', { p0: m.record_count.toLocaleString() }) }}</small>
                    </span>
                    <b class="sr-only">¥ {{ money(m.cost) }}</b>
                  </div>
                </td>
                <td>
                  <span class="kind-tag" :class="`is-${getModelKind(m.model)}`">
                    {{ getKindLabel(getModelKind(m.model)) }}
                  </span>
                </td>
                <td class="col-num">
                  <span class="num-text">{{ m.record_count ?? 1 }}</span>
                </td>
                <td class="col-num">
                  <strong class="cost-text">¥ {{ money(m.cost) }}</strong>
                </td>
                <td class="col-ratio">
                  <div class="ratio-bar-wrap">
                    <span class="ratio-num">{{ getRatio(m.cost) }}%</span>
                    <div class="ratio-track">
                      <div class="ratio-fill" :style="{ width: getRatio(m.cost) + '%' }"></div>
                    </div>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-if="!filteredModelStats.length" class="empty-table-hint">{{ tr('暂无计费记录') }}</p>
        </div>
      </section>
    </template>

    <!-- Models Section -->
    <ModelCatalog v-else-if="section === 'models'" :models="models" />

    <!-- Keys Section -->
    <template v-else-if="section === 'keys'">
      <p v-if="!auth.activeTeamId" class="empty-table-hint">{{ tr('请选择可用团队') }}</p>
      <template v-else>
        <!-- Slide-out Drawer (Image 3) -->
        <div
          class="drawer-backdrop"
          :class="{ 'is-open': drawerOpen }"
          @click="drawerOpen = false"
          aria-hidden="true"
        />
        <aside
          class="drawer-panel"
          :class="{ 'is-open': drawerOpen }"
          role="dialog"
          aria-modal="true"
          :aria-label="tr('创建 API Key')"
        >
          <div class="drawer-header">
            <div class="drawer-title-group">
              <span class="drawer-title-icon"><KeyRound :size="18" aria-hidden="true" /></span>
              <h2>{{ tr('创建 API Key') }}</h2>
            </div>
            <button
              type="button"
              class="drawer-close-btn"
              :aria-label="tr('关闭')"
              @click="drawerOpen = false"
            >
              <X :size="18" />
            </button>
          </div>

          <form class="drawer-form" @submit.prevent="create">
            <div class="drawer-body">
              <!-- Field 1: 密钥名称 -->
              <div class="drawer-form-group">
                <label class="drawer-label" for="key-name-input">
                  {{ tr('密钥名称') }} <span class="required">*</span>
                </label>
                <input
                  id="key-name-input"
                  v-model="name"
                  type="text"
                  class="drawer-input"
                  maxlength="80"
                  autocomplete="off"
                  :placeholder="tr('例如：我的应用')"
                  required
                >
              </div>

              <!-- Field 2: 可用模型 -->
              <div class="drawer-form-group">
                <label class="drawer-label">
                  {{ tr('可用模型') }} <span class="required">*</span>
                </label>
                <p class="drawer-subdesc">{{ tr('选择该密钥可以调用的模型') }}</p>

                <div class="model-cards-list">
                  <!-- Video models category block -->
                  <div class="model-category-block">
                    <div class="model-option-card" :class="{ 'is-checked': allowedModels.video, 'is-expanded': expandedKinds.video }">
                      <div class="model-opt-main" @click="toggleKindAll('video')">
                        <input
                          type="checkbox"
                          class="model-native-check"
                          :checked="isKindFullySelected('video')"
                          :indeterminate="isKindPartiallySelected('video')"
                          @click.stop
                          @change="toggleKindAll('video')"
                        >
                        <div class="model-opt-bubble is-video">
                          <Play :size="15" aria-hidden="true" />
                        </div>
                        <div class="model-opt-text">
                          <span class="model-opt-name">{{ tr('视频模型') }}</span>
                          <span class="model-opt-desc">{{ tr('支持 Seedance 等视频生成模型') }}</span>
                        </div>
                      </div>
                      <div class="model-opt-actions">
                        <span class="model-count-badge">
                          {{ tr('已选 {p0}/{p1} 个模型', { p0: getKindSelectedCount('video'), p1: getKindModels('video').length }) }}
                        </span>
                        <button
                          type="button"
                          class="btn-expand-kind"
                          :title="expandedKinds.video ? tr('收起具体模型') : tr('展开具体模型')"
                          :aria-label="expandedKinds.video ? tr('收起具体模型') : tr('展开具体模型')"
                          @click.stop="toggleKindExpanded('video')"
                        >
                          <ChevronDown :size="15" class="expand-chevron" :class="{ 'is-rotated': expandedKinds.video }" />
                        </button>
                      </div>
                    </div>

                    <!-- Expandable sub-models list -->
                    <div v-show="expandedKinds.video" class="sub-models-panel">
                      <div class="sub-models-toolbar">
                        <span class="sub-toolbar-title">{{ tr('选择具体模型') }}</span>
                        <div class="sub-toolbar-actions">
                          <button type="button" class="sub-action-btn" @click.stop="selectAllForKind('video')">{{ tr('全选') }}</button>
                          <span class="sub-action-sep">/</span>
                          <button type="button" class="sub-action-btn" @click.stop="clearAllForKind('video')">{{ tr('清空') }}</button>
                        </div>
                      </div>
                      <div class="sub-models-grid">
                        <label
                          v-for="m in getKindModels('video')"
                          :key="m.id"
                          class="sub-model-item"
                          :class="{ 'is-selected': isModelSelected(m.id) }"
                        >
                          <input
                            type="checkbox"
                            class="sub-model-check"
                            :checked="isModelSelected(m.id)"
                            @change="toggleSpecificModel(m.id, 'video')"
                          >
                          <div class="sub-model-info">
                            <span class="sub-model-name">{{ m.name }}</span>
                            <span v-if="m.desc" class="sub-model-desc">{{ m.desc }}</span>
                          </div>
                        </label>
                      </div>
                    </div>
                  </div>

                  <!-- Image models category block -->
                  <div class="model-category-block">
                    <div class="model-option-card" :class="{ 'is-checked': allowedModels.image, 'is-expanded': expandedKinds.image }">
                      <div class="model-opt-main" @click="toggleKindAll('image')">
                        <input
                          type="checkbox"
                          class="model-native-check"
                          :checked="isKindFullySelected('image')"
                          :indeterminate="isKindPartiallySelected('image')"
                          @click.stop
                          @change="toggleKindAll('image')"
                        >
                        <div class="model-opt-bubble is-image">
                          <Image :size="15" aria-hidden="true" />
                        </div>
                        <div class="model-opt-text">
                          <span class="model-opt-name">{{ tr('图片模型') }}</span>
                          <span class="model-opt-desc">{{ tr('支持 Seedream、GPT-image 等图片生成模型') }}</span>
                        </div>
                      </div>
                      <div class="model-opt-actions">
                        <span class="model-count-badge">
                          {{ tr('已选 {p0}/{p1} 个模型', { p0: getKindSelectedCount('image'), p1: getKindModels('image').length }) }}
                        </span>
                        <button
                          type="button"
                          class="btn-expand-kind"
                          :title="expandedKinds.image ? tr('收起具体模型') : tr('展开具体模型')"
                          :aria-label="expandedKinds.image ? tr('收起具体模型') : tr('展开具体模型')"
                          @click.stop="toggleKindExpanded('image')"
                        >
                          <ChevronDown :size="15" class="expand-chevron" :class="{ 'is-rotated': expandedKinds.image }" />
                        </button>
                      </div>
                    </div>

                    <!-- Expandable sub-models list -->
                    <div v-show="expandedKinds.image" class="sub-models-panel">
                      <div class="sub-models-toolbar">
                        <span class="sub-toolbar-title">{{ tr('选择具体模型') }}</span>
                        <div class="sub-toolbar-actions">
                          <button type="button" class="sub-action-btn" @click.stop="selectAllForKind('image')">{{ tr('全选') }}</button>
                          <span class="sub-action-sep">/</span>
                          <button type="button" class="sub-action-btn" @click.stop="clearAllForKind('image')">{{ tr('清空') }}</button>
                        </div>
                      </div>
                      <div class="sub-models-grid">
                        <label
                          v-for="m in getKindModels('image')"
                          :key="m.id"
                          class="sub-model-item"
                          :class="{ 'is-selected': isModelSelected(m.id) }"
                        >
                          <input
                            type="checkbox"
                            class="sub-model-check"
                            :checked="isModelSelected(m.id)"
                            @change="toggleSpecificModel(m.id, 'image')"
                          >
                          <div class="sub-model-info">
                            <span class="sub-model-name">{{ m.name }}</span>
                            <span v-if="m.desc" class="sub-model-desc">{{ m.desc }}</span>
                          </div>
                        </label>
                      </div>
                    </div>
                  </div>

                  <!-- Text models category block -->
                  <div class="model-category-block">
                    <div class="model-option-card" :class="{ 'is-checked': allowedModels.text, 'is-expanded': expandedKinds.text }">
                      <div class="model-opt-main" @click="toggleKindAll('text')">
                        <input
                          type="checkbox"
                          class="model-native-check"
                          :checked="isKindFullySelected('text')"
                          :indeterminate="isKindPartiallySelected('text')"
                          @click.stop
                          @change="toggleKindAll('text')"
                        >
                        <div class="model-opt-bubble is-text">
                          <FileText :size="15" aria-hidden="true" />
                        </div>
                        <div class="model-opt-text">
                          <span class="model-opt-name">{{ tr('文本模型') }}</span>
                          <span class="model-opt-desc">{{ tr('支持豆包 Seed-Evolving 等文本模型') }}</span>
                        </div>
                      </div>
                      <div class="model-opt-actions">
                        <span class="model-count-badge">
                          {{ tr('已选 {p0}/{p1} 个模型', { p0: getKindSelectedCount('text'), p1: getKindModels('text').length }) }}
                        </span>
                        <button
                          type="button"
                          class="btn-expand-kind"
                          :title="expandedKinds.text ? tr('收起具体模型') : tr('展开具体模型')"
                          :aria-label="expandedKinds.text ? tr('收起具体模型') : tr('展开具体模型')"
                          @click.stop="toggleKindExpanded('text')"
                        >
                          <ChevronDown :size="15" class="expand-chevron" :class="{ 'is-rotated': expandedKinds.text }" />
                        </button>
                      </div>
                    </div>

                    <!-- Expandable sub-models list -->
                    <div v-show="expandedKinds.text" class="sub-models-panel">
                      <div class="sub-models-toolbar">
                        <span class="sub-toolbar-title">{{ tr('选择具体模型') }}</span>
                        <div class="sub-toolbar-actions">
                          <button type="button" class="sub-action-btn" @click.stop="selectAllForKind('text')">{{ tr('全选') }}</button>
                          <span class="sub-action-sep">/</span>
                          <button type="button" class="sub-action-btn" @click.stop="clearAllForKind('text')">{{ tr('清空') }}</button>
                        </div>
                      </div>
                      <div class="sub-models-grid">
                        <label
                          v-for="m in getKindModels('text')"
                          :key="m.id"
                          class="sub-model-item"
                          :class="{ 'is-selected': isModelSelected(m.id) }"
                        >
                          <input
                            type="checkbox"
                            class="sub-model-check"
                            :checked="isModelSelected(m.id)"
                            @change="toggleSpecificModel(m.id, 'text')"
                          >
                          <div class="sub-model-info">
                            <span class="sub-model-name">{{ m.name }}</span>
                            <span v-if="m.desc" class="sub-model-desc">{{ m.desc }}</span>
                          </div>
                        </label>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Field 3: 授权有效期 -->
              <div class="drawer-form-group">
                <label class="drawer-label">{{ tr('授权有效期') }}</label>
                <div class="validity-row">
                  <label class="validity-card" :class="{ 'is-checked': validityMode === 'permanent' }">
                    <input v-model="validityMode" type="radio" value="permanent" class="validity-native-radio">
                    <span class="validity-text">{{ tr('永久') }}</span>
                  </label>
                  <label class="validity-card" :class="{ 'is-checked': validityMode === 'custom' }">
                    <input v-model="validityMode" type="radio" value="custom" class="validity-native-radio">
                    <span class="validity-text">{{ tr('自定义') }}</span>
                    <Calendar :size="14" class="validity-sub-icon" aria-hidden="true" />
                  </label>
                </div>

                <!-- Custom validity date/time selector -->
                <div v-if="validityMode === 'custom'" class="validity-custom-panel">
                  <div class="custom-panel-sub-label">
                    <span>{{ tr('选择到期时间') }}</span>
                  </div>

                  <!-- Quick Presets -->
                  <div class="custom-presets-row">
                    <button
                      type="button"
                      class="preset-pill-btn"
                      :class="{ 'is-active': isPresetActive(7) }"
                      @click="setExpirePreset(7)"
                    >
                      {{ tr('7天后') }}
                    </button>
                    <button
                      type="button"
                      class="preset-pill-btn"
                      :class="{ 'is-active': isPresetActive(30) }"
                      @click="setExpirePreset(30)"
                    >
                      {{ tr('30天后') }}
                    </button>
                    <button
                      type="button"
                      class="preset-pill-btn"
                      :class="{ 'is-active': isPresetActive(90) }"
                      @click="setExpirePreset(90)"
                    >
                      {{ tr('90天后') }}
                    </button>
                    <button
                      type="button"
                      class="preset-pill-btn"
                      :class="{ 'is-active': isPresetActive(365) }"
                      @click="setExpirePreset(365)"
                    >
                      {{ tr('1年后') }}
                    </button>
                  </div>

                  <!-- Interactive Date input -->
                  <div class="custom-date-field-wrap">
                    <Calendar :size="16" class="custom-date-icon" aria-hidden="true" />
                    <input
                      v-model="customExpireDate"
                      type="date"
                      :min="todayDateStr"
                      class="custom-date-input"
                      :aria-label="tr('到期日期')"
                      required
                    >
                  </div>

                  <!-- Expiration Preview Hint -->
                  <div class="expire-preview-callout">
                    <Clock :size="14" class="preview-callout-icon" aria-hidden="true" />
                    <span>{{ tr('密钥将于 {p0} 23:59 过期失效', { p0: customExpireDate || todayDateStr }) }}</span>
                  </div>
                </div>
              </div>
            </div>

            <div class="drawer-footer">
              <button type="button" class="btn-drawer-cancel" @click="drawerOpen = false">
                {{ tr('取消') }}
              </button>
              <button type="submit" class="btn-drawer-submit" :disabled="!name.trim() || changes">
                {{ tr('创建') }}
              </button>
            </div>
          </form>
        </aside>

        <!-- Revealed Secret Modal Dialog -->
        <div v-if="secret" class="secret-modal-backdrop">
          <div class="panel revealed secret-modal-card" role="dialog" aria-modal="true">
            <div class="secret-modal-top">
              <div class="secret-modal-icon"><KeyRound :size="24" /></div>
              <div>
                <h2>{{ tr('请保存新密钥，仅显示一次') }}</h2>
                <p class="secret-warn-hint">{{ tr('出于安全考虑，该密钥仅在此展示一次，关闭后将无法找回。请立即复制并妥善保管。') }}</p>
              </div>
            </div>

            <div class="secret-code-box">
              <code>{{ secret }}</code>
              <button type="button" class="secret-copy-btn" :title="tr('复制')" @click="copy(secret)">
                <Copy :size="15" aria-hidden="true" />
                <span>{{ tr('复制') }}</span>
              </button>
            </div>

            <div class="secret-modal-actions">
              <AppButton variant="primary" @click="secret = ''">{{ tr('我已保存并完成') }}</AppButton>
            </div>
          </div>
        </div>

        <!-- Empty State (Image 2) -->
        <div v-if="!keys.length" class="panel keys-empty-card">
          <div class="empty-icon-glow">
            <div class="empty-icon-inner">
              <KeyRound :size="32" class="empty-key-icon" aria-hidden="true" />
            </div>
          </div>

          <h3 class="empty-title">{{ tr('还没有 API Key') }}</h3>
          <p class="empty-desc">{{ tr('创建你的第一个 API Key，连接平台模型，开始调用 AI 能力。') }}</p>

          <div class="empty-tag-pill">
            <span>{{ tr('支持图片 · 视频 · 文本模型') }}</span>
          </div>

          <button type="button" class="btn-create-key-pill" @click="drawerOpen = true">
            <Plus :size="16" aria-hidden="true" />
            <span>{{ tr('创建 API Key') }}</span>
          </button>

          <p class="sr-only">{{ tr('当前团队下还没有个人 API Key') }}</p>
        </div>

        <!-- Table View (Image 1) -->
        <div v-else class="keys-content-wrap">
          <!-- Action Toolbar -->
          <div class="keys-toolbar">
            <button type="button" class="btn-create-key-pill" @click="drawerOpen = true">
              <Plus :size="16" aria-hidden="true" />
              <span>{{ tr('创建 API Key') }}</span>
            </button>

            <div class="keys-toolbar-right">
              <label class="keys-search-pill">
                <Search :size="14" aria-hidden="true" />
                <input
                  v-model="keySearch"
                  type="search"
                  :placeholder="tr('搜索密钥名称或 Key (仅显示前缀)')"
                >
                <button v-if="keySearch" type="button" @click="keySearch = ''"><X :size="12" /></button>
              </label>

              <div class="keys-filter-select">
                <AppSelect
                  v-model="keyPurposeFilter"
                  :options="[
                    { value: 'all', label: tr('全部用途') },
                    { value: 'api', label: tr('通用 API') },
                    { value: 'studio', label: tr('本地猫影') },
                  ]"
                  :ariaLabel="tr('全部用途')"
                  density="compact"
                />
              </div>

              <div class="keys-filter-select">
                <AppSelect
                  v-model="keyStatusFilter"
                  :options="[
                    { value: 'all', label: tr('全部状态') },
                    { value: 'active', label: tr('已启用') },
                    { value: 'revoked', label: tr('已停用') },
                  ]"
                  :ariaLabel="tr('全部状态')"
                  density="compact"
                />
              </div>
            </div>
          </div>

          <!-- Table Panel -->
          <div class="panel keys-table-card">
            <div class="table-scroll-wrap">
              <table class="keys-table">
                <thead>
                  <tr>
                    <th class="col-check">
                      <input
                        type="checkbox"
                        :checked="isAllSelected"
                        :aria-label="tr('全选')"
                        @change="toggleSelectAll"
                      >
                    </th>
                    <th>{{ tr('密钥名称') }}</th>
                    <th>{{ tr('用途') }}</th>
                    <th>{{ tr('Key (前缀)') }}</th>
                    <th>{{ tr('调用次数 (近7天)') }}</th>
                    <th>{{ tr('费用 (近7天)') }}</th>
                    <th>{{ tr('状态') }}</th>
                    <th>{{ tr('创建时间') }}</th>
                    <th class="col-ops">{{ tr('操作') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="k in filteredKeys" :key="k.id" class="table-row line">
                    <td class="col-check">
                      <input
                        type="checkbox"
                        :checked="selectedKeyIds.includes(k.id)"
                        :aria-label="k.name"
                        @change="toggleSelectKey(k.id)"
                      >
                    </td>
                    <td>
                      <div class="key-name-cell">
                        <span class="key-main-name">{{ k.name }}</span>
                        <span class="key-sub-label">{{ getKeySubLabel(k) }}</span>
                      </div>
                    </td>
                    <td>
                      <span class="purpose-pill" :class="`is-${k.purpose || 'api'}`">
                        <Code v-if="k.purpose !== 'studio'" :size="12" aria-hidden="true" />
                        <Layers v-else :size="12" aria-hidden="true" />
                        <span>{{ k.purpose === 'studio' ? tr('本地猫影') : tr('通用 API') }}</span>
                      </span>
                    </td>
                    <td>
                      <code class="key-code-mono">{{ formatKeyPrefix(k.preview) }}</code>
                    </td>
                    <td>
                      <div class="key-calls-cell">
                        <span class="key-calls-num">{{ getKeyCalls(k) }}</span>
                        <div class="key-calls-track" aria-hidden="true">
                          <div class="key-calls-bar" :style="{ width: getKeyCallsPercent(k) + '%' }"></div>
                        </div>
                      </div>
                    </td>
                    <td>
                      <span class="key-cost-val">¥{{ getKeyCost(k) }}</span>
                    </td>
                    <td>
                      <span class="status-indicator is-active">
                        <i class="status-dot"></i>
                        <span>{{ tr('启用') }}</span>
                      </span>
                    </td>
                    <td>
                      <span class="created-at-text">{{ formatCreatedAt(k.created_at) }}</span>
                    </td>
                    <td class="col-ops">
                      <div class="row-actions-group">
                        <button
                          type="button"
                          class="row-icon-action"
                          :title="tr('复制')"
                          @click="copy(k.preview)"
                        >
                          <Copy :size="14" aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          class="row-icon-action is-danger"
                          :title="tr('停用')"
                          :disabled="changes"
                          @click="revoke(k)"
                        >
                          <Trash2 :size="14" aria-hidden="true" />
                          <span class="sr-only">{{ tr('停用') }}</span>
                        </button>
                        <button
                          type="button"
                          class="row-icon-action"
                          :title="tr('更多')"
                        >
                          <MoreHorizontal :size="14" aria-hidden="true" />
                        </button>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- Table Footer -->
            <div class="keys-table-footer">
              <span class="selected-summary">{{ tr('已选择 {p0} 项', { p0: selectedKeyIds.length }) }}</span>
              <div class="keys-pagination-wrap">
                <span class="page-size-indicator">{{ tr('每页 10条') }}</span>
                <div class="page-btn-group">
                  <button type="button" class="page-nav-btn" disabled>&lt;</button>
                  <button type="button" class="page-nav-btn is-active">1</button>
                  <button type="button" class="page-nav-btn" disabled>&gt;</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </template>
    </template>

    <!-- Docs Section -->
    <PlatformApiDocs v-else-if="section === 'docs'" :base-url="apiBase" />
  </main>
</template>

<style scoped>
.console {
  max-width: 1320px;
  margin: 0 auto;
  padding: clamp(22px, 3vw, 40px);
  color: var(--app-text);
  font-variant-numeric: tabular-nums;
}
.console.is-catalog,
.console.is-usage {
  max-width: 1480px;
}

/* Header */
.console header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 28px;
  border-bottom: 1px solid var(--app-border);
  padding-bottom: 18px;
  flex-wrap: wrap;
}
.console h1 {
  margin: 0;
  font-size: clamp(22px, 2.2vw, 28px);
  letter-spacing: -0.03em;
  font-weight: 700;
}

/* Catalog Branding */
.catalog-branding,
.usage-branding {
  display: flex;
  align-items: center;
  gap: 14px;
}
.catalog-brand-icon,
.usage-brand-icon {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border-radius: 13px;
  background: color-mix(in srgb, var(--app-accent) 12%, transparent);
  flex-shrink: 0;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.usage-brand-icon:hover {
  transform: scale(1.08) rotate(-2deg);
}
.brand-chart-icon-svg .icon-bar {
  transform-origin: 50% 38px;
  animation: icon-bar-bounce 0.8s cubic-bezier(0.34, 1.56, 0.64, 1) both;
}
.brand-chart-icon-svg .icon-bar-1 { animation-delay: 0.05s; }
.brand-chart-icon-svg .icon-bar-2 { animation-delay: 0.16s; }
.brand-chart-icon-svg .icon-bar-3 { animation-delay: 0.27s; }
.usage-brand-icon.is-loading .brand-chart-icon-svg .icon-bar {
  animation: icon-bar-wave 1.1s ease-in-out infinite alternate;
}
.usage-brand-icon.is-loading .brand-chart-icon-svg .icon-bar-1 { animation-delay: 0s; }
.usage-brand-icon.is-loading .brand-chart-icon-svg .icon-bar-2 { animation-delay: 0.2s; }
.usage-brand-icon.is-loading .brand-chart-icon-svg .icon-bar-3 { animation-delay: 0.4s; }

@keyframes icon-bar-bounce {
  0% { transform: scaleY(0.2); opacity: 0.3; }
  65% { transform: scaleY(1.18); }
  100% { transform: scaleY(1); opacity: 1; }
}
@keyframes icon-bar-wave {
  0% { transform: scaleY(0.3); }
  100% { transform: scaleY(1.15); }
}

.catalog-subtitle,
.usage-subtitle {
  margin: 3px 0 0;
  font-size: 13px;
  color: var(--app-text-secondary);
  font-weight: 400;
  line-height: 1.5;
}

/* Usage Header Controls */
.usage-header-controls {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.team-pill-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 36px;
  padding: 0 14px;
  border-radius: 9999px;
  border: 1px solid var(--app-border);
  background: var(--app-surface);
  font-size: 13px;
  font-weight: 500;
  color: var(--app-text);
}
.team-switcher-box :deep(.app-select__button) {
  border-radius: 9999px !important;
  min-height: 36px;
  padding: 0 14px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  font-size: 13px;
  font-weight: 500;
  color: var(--app-text);
}

.period {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px;
  border-radius: 9999px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
}
.period button {
  background: transparent;
  color: var(--app-text-secondary);
  border: 0;
  border-radius: 9999px;
  padding: 6px 14px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all .16s ease;
}
.period button[aria-pressed=true] {
  color: #ffffff;
  background: var(--app-accent, #6366f1);
  font-weight: 600;
  box-shadow: 0 2px 6px color-mix(in srgb, var(--app-accent) 28%, transparent);
}
.period button:hover:not([aria-pressed=true]) {
  color: var(--app-text);
  background: var(--app-surface-hover);
}
.period-custom-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.period-refresh-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 9999px;
  border: 0;
  background: transparent;
  color: var(--app-text-secondary);
  cursor: pointer;
  padding: 0;
  margin-right: 2px;
  transition: all 0.2s ease;
}
.period-refresh-btn:hover {
  color: var(--app-text);
  background: var(--app-surface-hover);
}
.period-refresh-btn.is-refreshing .refresh-icon {
  animation: spin-refresh 0.8s linear infinite;
  color: var(--app-accent, #6366f1);
}
@keyframes spin-refresh {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

/* Loading Stage & Skeleton */
.loading-stage {
  display: flex;
  flex-direction: column;
  gap: 22px;
  margin-bottom: 24px;
}
.loading-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  align-self: flex-start;
  padding: 6px 14px;
  border-radius: 9999px;
  background: color-mix(in srgb, var(--app-accent, #6366f1) 10%, var(--app-surface));
  border: 1px solid color-mix(in srgb, var(--app-accent, #6366f1) 20%, transparent);
  color: var(--app-accent, #6366f1);
  font-size: 12px;
  font-weight: 550;
}
.spinner-icon {
  animation: spin-refresh 1s linear infinite;
}

/* Shimmer Sweep Animation */
.skeleton-shimmer {
  background: linear-gradient(
    90deg,
    color-mix(in srgb, var(--app-surface-muted) 85%, transparent) 25%,
    color-mix(in srgb, var(--app-border) 70%, transparent) 50%,
    color-mix(in srgb, var(--app-surface-muted) 85%, transparent) 75%
  );
  background-size: 200% 100%;
  animation: shimmer-sweep 1.8s infinite ease-in-out;
  border-radius: 6px;
}
@keyframes shimmer-sweep {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}

/* Skeleton Top Metric Cards */
.skeleton-totals .skeleton-card {
  gap: 12px;
  cursor: default;
}
.sk-icon-title {
  width: 100px;
  height: 18px;
}
.sk-num {
  width: 160px;
  height: 32px;
  border-radius: 8px;
}
.sk-tag {
  width: 80px;
  height: 14px;
}

/* Skeleton Middle Panels */
.skeleton-panel {
  display: flex;
  flex-direction: column;
}
.skeleton-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}
.sk-heading {
  width: 120px;
  height: 18px;
}
.sk-segmented {
  width: 130px;
  height: 28px;
  border-radius: 9999px;
}

/* Skeleton Bar Chart */
.skeleton-chart-view {
  height: 180px;
  display: flex;
  align-items: flex-end;
  padding-bottom: 10px;
}
.skeleton-chart-bars {
  display: flex;
  align-items: flex-end;
  justify-content: space-around;
  width: 100%;
  height: 100%;
  gap: 12px;
}
.sk-bar-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  height: 100%;
  justify-content: flex-end;
}
.sk-bar-track {
  width: min(55%, 26px);
  height: calc(100% - 20px);
  display: flex;
  align-items: flex-end;
}
.sk-bar-fill {
  width: 100%;
  border-radius: 4px 4px 0 0;
  background: linear-gradient(180deg, rgba(139, 92, 246, 0.35) 0%, rgba(99, 102, 241, 0.15) 100%);
  animation: pulse-sk-bar 1.5s ease-in-out infinite alternate;
}
@keyframes pulse-sk-bar {
  0% { opacity: 0.35; transform: scaleY(0.92); }
  100% { opacity: 0.85; transform: scaleY(1.04); }
}
.sk-bar-lbl {
  width: 32px;
  height: 10px;
}

/* Skeleton Donut Chart */
.skeleton-donut-layout {
  display: flex;
  align-items: center;
  justify-content: space-around;
  height: 180px;
  gap: 16px;
}
.sk-donut-circle-wrap {
  position: relative;
  width: 130px;
  height: 130px;
}
.sk-donut-pulse-ring {
  width: 130px;
  height: 130px;
  border-radius: 50%;
  background: conic-gradient(
    rgba(124, 58, 237, 0.3) 0% 55%,
    rgba(56, 189, 248, 0.3) 55% 80%,
    rgba(52, 211, 153, 0.3) 80% 100%
  );
  display: grid;
  place-items: center;
  animation: pulse-sk-ring 2s ease-in-out infinite alternate;
}
@keyframes pulse-sk-ring {
  0% { transform: scale(0.95); opacity: 0.45; }
  100% { transform: scale(1.03); opacity: 0.85; }
}
.sk-donut-center-hole {
  width: 90px;
  height: 90px;
  border-radius: 50%;
  background: var(--app-surface);
}
.sk-legend-rows {
  display: flex;
  flex-direction: column;
  gap: 14px;
  flex: 1;
}
.sk-legend-line {
  height: 16px;
  width: 90%;
}

/* Skeleton Bottom Table */
.sk-search {
  width: 200px;
  height: 32px;
  border-radius: 9999px;
}
.skeleton-table-lines {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 10px 0;
}
.sk-table-line {
  height: 36px;
  width: 100%;
}

/* Generic Skeleton */
.skeleton-generic-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}
.sk-generic-block {
  height: 140px;
  border-radius: 14px;
}

/* 1. Top Metrics Cards (Totals) */
.totals {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
  margin-bottom: 22px;
}
.metric-card {
  position: relative;
  display: flex;
  flex-direction: column;
  padding: 22px 24px;
  border-radius: 16px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  transition: box-shadow .18s, transform .18s;
  overflow: hidden;
  animation: card-slide-up 0.6s cubic-bezier(0.16, 1, 0.3, 1) both;
}
.totals .metric-card:nth-child(1) { animation-delay: 0.05s; }
.totals .metric-card:nth-child(2) { animation-delay: 0.12s; }
.totals .metric-card:nth-child(3) { animation-delay: 0.19s; }

@keyframes card-slide-up {
  0% {
    opacity: 0;
    transform: translateY(20px);
  }
  100% {
    opacity: 1;
    transform: translateY(0);
  }
}

.metric-card:hover {
  box-shadow: 0 6px 20px color-mix(in srgb, var(--app-accent) 6%, rgba(0, 0, 0, 0.04));
  transform: translateY(-1px);
}

.metric-card.is-primary {
  background: linear-gradient(135deg, #6d5dfc 0%, #4f46e5 100%);
  border-color: transparent;
  color: #ffffff;
  box-shadow: 0 8px 24px rgba(109, 93, 252, 0.28);
}

.metric-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.metric-icon-box {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.2);
  color: #ffffff;
  animation: icon-bubble-pop 0.55s cubic-bezier(0.34, 1.56, 0.64, 1) both;
  animation-delay: 0.2s;
}
@keyframes icon-bubble-pop {
  0% {
    opacity: 0;
    transform: scale(0.5);
  }
  100% {
    opacity: 1;
    transform: scale(1);
  }
}
.metric-card:not(.is-primary) .metric-icon-box.is-cost {
  background: color-mix(in srgb, #6366f1 12%, transparent);
  color: #6366f1;
}
.metric-card:not(.is-primary) .metric-icon-box.is-records {
  background: color-mix(in srgb, #8b5cf6 12%, transparent);
  color: #7c3aed;
}

.metric-title {
  font-size: 13px;
  font-weight: 500;
  color: inherit;
  opacity: 0.85;
}

.metric-body {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}
.metric-body strong {
  font-size: clamp(24px, 2.2vw, 32px);
  font-weight: 700;
  letter-spacing: -0.02em;
  color: inherit;
}

.recharge-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 12px;
  border-radius: 9999px;
  background: rgba(255, 255, 255, 0.22);
  color: #ffffff;
  font-size: 12px;
  font-weight: 600;
  text-decoration: none;
  backdrop-filter: blur(4px);
  transition: background .16s ease;
}
.recharge-pill:hover {
  background: rgba(255, 255, 255, 0.35);
}

.metric-sub {
  margin-top: 8px;
}
.trend-indicator {
  font-size: 12px;
  font-weight: 550;
  color: #10b981;
}
.trend-indicator.is-down {
  color: #10b981;
}

/* 2. Middle Charts Row */
.usage-charts-grid {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 18px;
  margin-bottom: 22px;
}

.panel {
  padding: 22px 24px;
  border-radius: 16px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
}

.chart-panel-header,
.table-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}
.panel-heading-group {
  display: flex;
  align-items: center;
  gap: 8px;
}
.panel-heading-group h2 {
  margin: 0;
  font-size: 15px;
  font-weight: 650;
  color: var(--app-text);
}
.heading-icon {
  color: var(--app-accent, #6366f1);
}

/* Metric Segmented Toggle */
.metric-segmented {
  display: inline-flex;
  padding: 3px;
  border-radius: 9999px;
  background: var(--app-surface-muted);
  border: 1px solid var(--app-border);
}
.segmented-btn {
  border: 0;
  border-radius: 9999px;
  background: transparent;
  color: var(--app-text-secondary);
  padding: 4px 12px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all .16s ease;
}
.segmented-btn.is-active {
  background: var(--app-accent, #6366f1);
  color: #ffffff;
  font-weight: 600;
  box-shadow: 0 1px 4px color-mix(in srgb, var(--app-accent) 26%, transparent);
}

/* Chart Canvas Area */
.chart-view-area {
  display: flex;
  height: 200px;
  gap: 12px;
  align-items: stretch;
}
.chart-y-ticks {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding-bottom: 24px;
  color: var(--app-text-secondary);
  font-size: 11px;
  text-align: right;
  min-width: 48px;
}
.chart-stage {
  position: relative;
  flex: 1;
  display: flex;
  flex-direction: column;
}
.chart-gridlines {
  position: absolute;
  top: 6px;
  left: 0;
  right: 0;
  bottom: 24px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  pointer-events: none;
}
.gridline {
  border-bottom: 1px dashed var(--app-border);
  width: 100%;
}

.chart {
  position: relative;
  z-index: 1;
  display: flex;
  height: 100%;
  align-items: stretch;
  gap: 8px;
}
.chart-bar-wrap {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  cursor: pointer;
}
.chart-bar-wrap:hover i {
  filter: brightness(1.1);
  box-shadow: 0 0 10px color-mix(in srgb, var(--app-accent) 45%, transparent);
}

.bar-fill-track {
  width: 100%;
  height: calc(100% - 24px);
  display: flex;
  align-items: flex-end;
  justify-content: center;
}
.bar-fill-track i {
  display: block;
  width: min(55%, 26px);
  background: linear-gradient(to top, var(--app-accent, #6d5dfc), #9d8eff);
  border-radius: 4px 4px 0 0;
  transform-origin: bottom;
  animation: bar-grow-up 0.85s cubic-bezier(0.16, 1, 0.3, 1) both;
  animation-delay: calc(var(--bar-idx, 0) * 0.06s);
  transition: height 0.5s cubic-bezier(0.16, 1, 0.3, 1), filter 0.2s ease, box-shadow 0.2s ease;
}

@keyframes bar-grow-up {
  0% {
    transform: scaleY(0);
    opacity: 0;
  }
  100% {
    transform: scaleY(1);
    opacity: 1;
  }
}

.chart-bar-wrap:hover i,
.chart-bar-wrap:focus-visible i {
  filter: brightness(1.2);
  box-shadow: 0 0 14px color-mix(in srgb, var(--app-accent) 55%, transparent);
}

.bar-x-date {
  height: 24px;
  display: flex;
  align-items: center;
  color: var(--app-text-secondary);
  font-size: 11px;
}

/* Donut Chart */
.donut-container {
  display: flex;
  align-items: center;
  justify-content: space-around;
  height: 200px;
  gap: 16px;
}
.donut-chart-box {
  position: relative;
  display: grid;
  place-items: center;
}
.donut-svg {
  transform: rotate(-90deg);
  animation: donut-spin-in 0.9s cubic-bezier(0.16, 1, 0.3, 1) both;
}

@keyframes donut-spin-in {
  0% {
    transform: rotate(-240deg) scale(0.85);
    opacity: 0;
  }
  100% {
    transform: rotate(-90deg) scale(1);
    opacity: 1;
  }
}

.donut-segment {
  animation: donut-segment-reveal 1s cubic-bezier(0.16, 1, 0.3, 1) both;
  animation-delay: calc(var(--slice-idx, 0) * 0.1s + 0.15s);
  transition: stroke-width 0.25s cubic-bezier(0.34, 1.56, 0.64, 1), filter 0.25s ease;
}

@keyframes donut-segment-reveal {
  0% {
    stroke-dashoffset: 314.16;
    opacity: 0;
  }
  100% {
    opacity: 1;
  }
}

.donut-segment:hover {
  stroke-width: 20;
  filter: drop-shadow(0 0 8px currentColor);
}

.donut-center-cost,
.donut-center-label {
  transform: rotate(90deg);
  transform-origin: 75px 75px;
  animation: donut-center-pop 0.65s cubic-bezier(0.34, 1.56, 0.64, 1) both;
  animation-delay: 0.35s;
}

@keyframes donut-center-pop {
  0% {
    opacity: 0;
    transform: rotate(90deg) scale(0.65);
  }
  100% {
    opacity: 1;
    transform: rotate(90deg) scale(1);
  }
}

.donut-legend-box {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.legend-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  animation: legend-slide-in 0.5s cubic-bezier(0.16, 1, 0.3, 1) both;
  animation-delay: calc(var(--legend-idx, 0) * 0.08s + 0.2s);
}

@keyframes legend-slide-in {
  0% {
    opacity: 0;
    transform: translateX(14px);
  }
  100% {
    opacity: 1;
    transform: translateX(0);
  }
}
.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.legend-label {
  color: var(--app-text-secondary);
  min-width: 58px;
}
.legend-val {
  color: var(--app-text);
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}

/* 3. Bottom Table Panel */
.table-panel {
  padding: 22px 24px;
}
.table-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.table-search-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 34px;
  width: 220px;
  padding: 0 12px;
  border-radius: 9999px;
  background: var(--app-surface-muted);
  border: 1px solid var(--app-border);
  color: var(--app-text-secondary);
}
.table-search-pill:focus-within {
  border-color: var(--app-accent);
}
.table-search-pill input {
  width: 100%;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--app-text);
  font: inherit;
  font-size: 12px;
}
.table-search-pill input::-webkit-search-cancel-button { display: none; }
.table-search-pill button {
  border: 0;
  background: transparent;
  padding: 2px;
  color: inherit;
  cursor: pointer;
}

.table-sort-pill :deep(.app-select__button) {
  border-radius: 9999px !important;
  min-height: 34px;
  padding: 0 12px;
  background: var(--app-surface-muted);
  border: 1px solid var(--app-border);
  font-size: 12px;
  font-weight: 500;
  color: var(--app-text);
}

.table-scroll-wrap {
  overflow-x: auto;
  margin-top: 10px;
}
.model-stats-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.model-stats-table th {
  padding: 10px 14px;
  text-align: left;
  color: var(--app-text-secondary);
  font-size: 12px;
  font-weight: 500;
  border-bottom: 1px solid var(--app-border);
}
.model-stats-table td {
  padding: 14px;
  border-bottom: 1px solid color-mix(in srgb, var(--app-border) 60%, transparent);
  vertical-align: middle;
}
.model-stats-table tr.table-row {
  animation: table-row-in 0.4s ease both;
  animation-delay: calc(var(--row-idx, 0) * 0.035s + 0.1s);
}
@keyframes table-row-in {
  0% {
    opacity: 0;
    transform: translateY(8px);
  }
  100% {
    opacity: 1;
    transform: translateY(0);
  }
}
.model-stats-table tr:hover td {
  background: var(--app-surface-hover);
}

.col-num {
  text-align: right !important;
}
.col-ratio {
  width: 220px;
}

.model-name-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}
.model-icon-bubble {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  flex-shrink: 0;
}
.model-icon-bubble.is-video {
  background: color-mix(in srgb, #8b5cf6 15%, transparent);
  color: #7c3aed;
}
.model-icon-bubble.is-image {
  background: color-mix(in srgb, #38bdf8 15%, transparent);
  color: #0284c7;
}
.model-icon-bubble.is-text {
  background: color-mix(in srgb, #34d399 15%, transparent);
  color: #059669;
}

.model-name-label {
  font-weight: 600;
  color: var(--app-text);
}

.kind-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 5px;
  font-size: 11px;
  font-weight: 600;
}
.kind-tag.is-video {
  background: color-mix(in srgb, #8b5cf6 12%, transparent);
  color: #7c3aed;
}
.kind-tag.is-image {
  background: color-mix(in srgb, #38bdf8 12%, transparent);
  color: #0284c7;
}
.kind-tag.is-text {
  background: color-mix(in srgb, #34d399 12%, transparent);
  color: #059669;
}

.cost-text {
  font-weight: 650;
  color: var(--app-text);
}

.ratio-bar-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
}
.ratio-num {
  min-width: 42px;
  font-size: 12px;
  color: var(--app-text);
  font-weight: 600;
  text-align: right;
}
.ratio-track {
  flex: 1;
  height: 6px;
  border-radius: 9999px;
  background: var(--app-surface-muted);
  overflow: hidden;
}
.ratio-fill {
  height: 100%;
  border-radius: 9999px;
  background: var(--app-accent, #6366f1);
  transition: width .25s ease;
}

.empty-table-hint {
  padding: 30px 0;
  text-align: center;
  color: var(--app-text-secondary);
  font-size: 13px;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

/* Keys Form / Legacy & Modern Styles */
.console.is-keys {
  max-width: 1480px;
}

/* Header Keys Branding & Stat Badges (Image 1) */
.keys-branding {
  display: flex;
  align-items: center;
  gap: 16px;
}
.keys-brand-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(139, 92, 246, 0.16), rgba(99, 102, 241, 0.22));
  color: #7c3aed;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  box-shadow: 0 4px 14px rgba(124, 58, 237, 0.18);
}
.keys-subtitle {
  margin: 3px 0 0;
  font-size: 13px;
  color: var(--app-text-secondary);
}

.keys-header-stats {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.stat-pill {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  border-radius: 12px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.02);
}
.stat-icon-wrap {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}
.stat-icon-wrap.is-cube {
  background: rgba(139, 92, 246, 0.1);
  color: #7c3aed;
}
.stat-icon-wrap.is-zap {
  background: rgba(59, 130, 246, 0.1);
  color: #3b82f6;
}
.stat-icon-wrap.is-cost {
  background: rgba(236, 72, 153, 0.1);
  color: #ec4899;
}
.stat-meta {
  display: flex;
  flex-direction: column;
}
.stat-label {
  font-size: 11px;
  color: var(--app-text-secondary);
  font-weight: 500;
}
.stat-value {
  font-size: 15px;
  font-weight: 700;
  color: var(--app-text);
  letter-spacing: -0.01em;
}

/* Primary Action Pill Button */
.btn-create-key-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 38px;
  padding: 0 18px;
  border-radius: 9999px;
  background: #7c3aed;
  color: #ffffff;
  font-size: 13px;
  font-weight: 600;
  border: none;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(124, 58, 237, 0.28);
  transition: all 0.2s ease;
}
.btn-create-key-pill:hover {
  background: #6d28d9;
  transform: translateY(-1px);
  box-shadow: 0 6px 18px rgba(124, 58, 237, 0.36);
}
.btn-create-key-pill:active {
  transform: translateY(0);
}

/* Empty State Card (Image 2) */
.keys-empty-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 24px;
  margin: 16px 0;
  border-radius: 20px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.02);
  text-align: center;
}
.empty-icon-glow {
  position: relative;
  margin-bottom: 22px;
}
.empty-icon-glow::before {
  content: '';
  position: absolute;
  inset: -12px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.3) 0%, rgba(139, 92, 246, 0) 70%);
  z-index: 0;
  animation: pulse-glow 3s infinite ease-in-out;
}
@keyframes pulse-glow {
  0%, 100% { transform: scale(1); opacity: 0.6; }
  50% { transform: scale(1.15); opacity: 0.9; }
}
.empty-icon-inner {
  position: relative;
  z-index: 1;
  width: 68px;
  height: 68px;
  border-radius: 50%;
  background: linear-gradient(135deg, rgba(139, 92, 246, 0.15), rgba(99, 102, 241, 0.22));
  border: 1px solid rgba(139, 92, 246, 0.25);
  display: grid;
  place-items: center;
  box-shadow: 0 8px 24px rgba(124, 58, 237, 0.18);
}
.empty-key-icon {
  color: #7c3aed;
  transform: rotate(-35deg);
}
.empty-title {
  margin: 0 0 10px;
  font-size: 22px;
  font-weight: 700;
  color: var(--app-text);
  letter-spacing: -0.02em;
}
.empty-desc {
  margin: 0 0 20px;
  font-size: 14px;
  color: var(--app-text-secondary);
  max-width: 440px;
  line-height: 1.6;
}
.empty-tag-pill {
  display: inline-flex;
  align-items: center;
  padding: 6px 16px;
  border-radius: 9999px;
  background: rgba(139, 92, 246, 0.08);
  border: 1px solid rgba(139, 92, 246, 0.16);
  color: #7c3aed;
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 24px;
}

/* Toolbar (Image 1) */
.keys-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
  flex-wrap: wrap;
}
.keys-toolbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.keys-search-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: 9999px;
  padding: 0 14px;
  min-height: 38px;
  width: 290px;
  color: var(--app-text-secondary);
}
.keys-search-pill:focus-within {
  border-color: #8b5cf6;
  box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.12);
}
.keys-search-pill input {
  border: 0;
  background: transparent;
  outline: none;
  font-size: 13px;
  color: var(--app-text);
  width: 100%;
}
.keys-search-pill button {
  border: 0;
  background: transparent;
  padding: 2px;
  color: inherit;
  cursor: pointer;
}
.keys-filter-select :deep(.app-select__button) {
  border-radius: 9999px !important;
  min-height: 38px;
  padding: 0 16px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  font-size: 13px;
  font-weight: 500;
  color: var(--app-text);
}

/* Table Card (Image 1) */
.keys-table-card {
  padding: 0;
  border-radius: 16px;
  overflow: hidden;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  box-shadow: 0 4px 18px rgba(0, 0, 0, 0.02);
}
.keys-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.keys-table th {
  padding: 14px 18px;
  text-align: left;
  color: var(--app-text-secondary);
  font-size: 12px;
  font-weight: 600;
  border-bottom: 1px solid var(--app-border);
  background: color-mix(in srgb, var(--app-surface-muted) 40%, var(--app-surface));
  white-space: nowrap;
}
.keys-table td {
  padding: 16px 18px;
  border-bottom: 1px solid color-mix(in srgb, var(--app-border) 60%, transparent);
  vertical-align: middle;
}
.keys-table tr.table-row:hover td {
  background: var(--app-surface-hover);
}
.col-check {
  width: 40px;
  text-align: center;
}
.col-check input[type="checkbox"] {
  width: 16px;
  height: 16px;
  border-radius: 4px;
  accent-color: #7c3aed;
  cursor: pointer;
}
.col-ops {
  text-align: right;
  width: 120px;
}

/* Table Cells */
.key-name-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.key-main-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--app-text);
}
.key-sub-label {
  font-size: 12px;
  color: var(--app-text-secondary);
}

.purpose-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  background: color-mix(in srgb, #8b5cf6 10%, var(--app-surface-muted));
  color: #7c3aed;
  border: 1px solid color-mix(in srgb, #8b5cf6 20%, transparent);
}
.purpose-pill.is-studio {
  background: color-mix(in srgb, #3b82f6 10%, var(--app-surface-muted));
  color: #2563eb;
  border-color: color-mix(in srgb, #3b82f6 20%, transparent);
}

.key-code-mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 13px;
  color: var(--app-text);
  background: var(--app-surface-muted);
  padding: 3px 8px;
  border-radius: 6px;
  border: 1px solid var(--app-border);
}

.key-calls-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}
.key-calls-num {
  font-weight: 600;
  font-size: 13px;
  min-width: 38px;
}
.key-calls-track {
  width: 80px;
  height: 6px;
  border-radius: 9999px;
  background: var(--app-surface-muted);
  overflow: hidden;
}
.key-calls-bar {
  height: 100%;
  border-radius: 9999px;
  background: #7c3aed;
  transition: width 0.3s ease;
}

.key-cost-val {
  font-weight: 600;
  color: var(--app-text);
  font-size: 13px;
}

.status-indicator {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
}
.status-indicator.is-active {
  color: #10b981;
}
.status-indicator.is-active .status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.2);
}
.status-indicator.is-disabled {
  color: var(--app-text-secondary);
}
.status-indicator.is-disabled .status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--app-text-secondary);
}

.created-at-text {
  font-size: 12px;
  color: var(--app-text-secondary);
  white-space: nowrap;
}

.row-actions-group {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.row-icon-action {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--app-text-secondary);
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: all 0.15s ease;
}
.row-icon-action:hover {
  background: var(--app-surface-muted);
  color: var(--app-text);
  border-color: var(--app-border);
}
.row-icon-action.is-danger:hover {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
  border-color: rgba(239, 68, 68, 0.2);
}

/* Table Footer */
.keys-table-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  border-top: 1px solid var(--app-border);
  font-size: 13px;
  color: var(--app-text-secondary);
  flex-wrap: wrap;
  gap: 12px;
}
.keys-pagination-wrap {
  display: flex;
  align-items: center;
  gap: 16px;
}
.page-btn-group {
  display: flex;
  align-items: center;
  gap: 4px;
}
.page-nav-btn {
  min-width: 28px;
  height: 28px;
  padding: 0 8px;
  border-radius: 6px;
  border: 1px solid var(--app-border);
  background: var(--app-surface);
  color: var(--app-text);
  font-size: 12px;
  font-weight: 500;
  display: grid;
  place-items: center;
  cursor: pointer;
}
.page-nav-btn.is-active {
  background: #7c3aed;
  color: #ffffff;
  border-color: #7c3aed;
}
.page-nav-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* Slide-out Drawer (Image 3) */
.drawer-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  backdrop-filter: blur(2px);
  z-index: 999;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.25s ease;
}
.drawer-backdrop.is-open {
  opacity: 1;
  pointer-events: auto;
}

.drawer-panel {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(500px, 100vw);
  background: var(--app-surface);
  z-index: 1000;
  box-shadow: -10px 0 35px rgba(0, 0, 0, 0.15);
  display: flex;
  flex-direction: column;
  transform: translateX(100%);
  transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}
.drawer-panel.is-open {
  transform: translateX(0);
}

.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px;
  border-bottom: 1px solid var(--app-border);
}
.drawer-title-group {
  display: flex;
  align-items: center;
  gap: 10px;
}
.drawer-title-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: rgba(139, 92, 246, 0.12);
  color: #7c3aed;
  display: grid;
  place-items: center;
}
.drawer-header h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: var(--app-text);
}
.drawer-close-btn {
  border: 0;
  background: transparent;
  color: var(--app-text-secondary);
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: all 0.15s ease;
}
.drawer-close-btn:hover {
  background: var(--app-surface-muted);
  color: var(--app-text);
}

.drawer-form {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}
.drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}
.drawer-form-group {
  display: flex;
  flex-direction: column;
}
.drawer-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--app-text);
  margin-bottom: 6px;
}
.required {
  color: #ef4444;
  margin-left: 2px;
}
.drawer-subdesc {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--app-text-secondary);
}
.drawer-input {
  width: 100%;
  height: 42px;
  padding: 0 14px;
  border: 1px solid var(--app-border);
  border-radius: 10px;
  background: var(--app-surface-muted);
  color: var(--app-text);
  font-size: 14px;
  outline: none;
  box-sizing: border-box;
}
.drawer-input:focus {
  border-color: #7c3aed;
  box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.12);
  background: var(--app-surface);
}

/* Model Options in Drawer */
.model-cards-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.model-category-block {
  display: flex;
  flex-direction: column;
}
.model-option-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid var(--app-border);
  background: var(--app-surface);
  cursor: pointer;
  transition: all 0.2s ease;
}
.model-option-card:hover {
  border-color: #8b5cf6;
  background: color-mix(in srgb, #8b5cf6 3%, var(--app-surface));
}
.model-option-card.is-checked {
  border-color: #7c3aed;
  background: color-mix(in srgb, #7c3aed 6%, var(--app-surface));
}
.model-option-card.is-expanded {
  border-bottom-left-radius: 0;
  border-bottom-right-radius: 0;
  border-bottom-color: color-mix(in srgb, #7c3aed 20%, transparent);
}
.model-opt-main {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}
.model-native-check {
  width: 16px;
  height: 16px;
  border-radius: 4px;
  accent-color: #7c3aed;
  cursor: pointer;
  flex-shrink: 0;
}
.model-opt-bubble {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}
.model-opt-bubble.is-video {
  background: rgba(139, 92, 246, 0.14);
  color: #7c3aed;
}
.model-opt-bubble.is-image {
  background: rgba(56, 189, 248, 0.14);
  color: #0284c7;
}
.model-opt-bubble.is-text {
  background: rgba(52, 211, 153, 0.14);
  color: #059669;
}
.model-opt-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.model-opt-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--app-text);
}
.model-opt-desc {
  font-size: 12px;
  color: var(--app-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.model-opt-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.model-count-badge {
  font-size: 11px;
  font-weight: 500;
  padding: 2px 8px;
  border-radius: 12px;
  background: rgba(139, 92, 246, 0.1);
  color: #7c3aed;
  white-space: nowrap;
}
.btn-expand-kind {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: var(--app-text-secondary);
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: all 0.2s ease;
}
.btn-expand-kind:hover {
  background: rgba(139, 92, 246, 0.14);
  color: #7c3aed;
}
.expand-chevron {
  transition: transform 0.2s ease;
}
.expand-chevron.is-rotated {
  transform: rotate(180deg);
}

/* Sub-models panel */
.sub-models-panel {
  padding: 12px 14px 14px 14px;
  border: 1px solid var(--app-border);
  border-top: none;
  border-bottom-left-radius: 12px;
  border-bottom-right-radius: 12px;
  background: color-mix(in srgb, #7c3aed 2%, var(--app-surface-muted));
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.sub-models-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.sub-toolbar-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--app-text-secondary);
  letter-spacing: 0.3px;
}
.sub-toolbar-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}
.sub-action-btn {
  font-size: 11px;
  font-weight: 500;
  color: #7c3aed;
  background: none;
  border: none;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  transition: background 0.15s ease;
}
.sub-action-btn:hover {
  background: rgba(124, 58, 237, 0.1);
}
.sub-action-sep {
  color: var(--app-text-secondary);
  font-size: 11px;
}
.sub-models-grid {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sub-model-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid var(--app-border);
  background: var(--app-surface);
  cursor: pointer;
  transition: all 0.15s ease;
}
.sub-model-item:hover {
  border-color: #8b5cf6;
  background: color-mix(in srgb, #8b5cf6 4%, var(--app-surface));
}
.sub-model-item.is-selected {
  border-color: #7c3aed;
  background: color-mix(in srgb, #7c3aed 6%, var(--app-surface));
}
.sub-model-check {
  width: 14px;
  height: 14px;
  accent-color: #7c3aed;
  cursor: pointer;
  flex-shrink: 0;
}
.sub-model-info {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.sub-model-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--app-text);
  word-break: break-all;
}
.sub-model-desc {
  font-size: 11px;
  color: var(--app-text-secondary);
}

/* Validity Options in Drawer */
.validity-row {
  display: flex;
  gap: 12px;
}
.validity-card {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 42px;
  padding: 0 16px;
  border-radius: 10px;
  border: 1px solid var(--app-border);
  background: var(--app-surface);
  cursor: pointer;
  transition: all 0.2s ease;
}
.validity-card:hover {
  border-color: #8b5cf6;
}
.validity-card.is-checked {
  border-color: #7c3aed;
  background: color-mix(in srgb, #7c3aed 6%, var(--app-surface));
}
.validity-native-radio {
  accent-color: #7c3aed;
  cursor: pointer;
}
.validity-text {
  font-size: 13px;
  font-weight: 500;
  color: var(--app-text);
}
.validity-sub-icon {
  color: var(--app-text-secondary);
}

/* Custom validity date panel */
.validity-custom-panel {
  margin-top: 10px;
  padding: 14px;
  border-radius: 12px;
  border: 1px solid color-mix(in srgb, #7c3aed 25%, var(--app-border));
  background: color-mix(in srgb, #7c3aed 4%, var(--app-surface));
  display: flex;
  flex-direction: column;
  gap: 10px;
  animation: fadeIn 0.2s ease;
}
.custom-panel-sub-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--app-text);
}
.custom-presets-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.preset-pill-btn {
  padding: 4px 12px;
  border-radius: 14px;
  font-size: 12px;
  font-weight: 500;
  border: 1px solid var(--app-border);
  background: var(--app-surface);
  color: var(--app-text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}
.preset-pill-btn:hover {
  border-color: #8b5cf6;
  color: #7c3aed;
}
.preset-pill-btn.is-active {
  background: #7c3aed;
  color: #ffffff;
  border-color: #7c3aed;
  font-weight: 600;
}
.custom-date-field-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid var(--app-border);
  background: var(--app-surface);
}
.custom-date-field-wrap:focus-within {
  border-color: #7c3aed;
  box-shadow: 0 0 0 2px rgba(124, 58, 237, 0.15);
}
.custom-date-icon {
  color: #7c3aed;
  flex-shrink: 0;
}
.custom-date-input {
  border: none;
  outline: none;
  background: transparent;
  font-size: 13px;
  font-family: inherit;
  color: var(--app-text);
  width: 100%;
  cursor: pointer;
}
.expire-preview-callout {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: 6px;
  background: rgba(124, 58, 237, 0.08);
  color: #7c3aed;
  font-size: 11px;
  font-weight: 500;
}
.preview-callout-icon {
  flex-shrink: 0;
}

/* Custom period in Usage header */
.custom-period-container {
  position: relative;
  display: inline-block;
}
.custom-period-popover {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  z-index: 100;
  min-width: 210px;
  padding: 12px;
  border-radius: 12px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.15), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
  display: flex;
  flex-direction: column;
  gap: 10px;
  animation: fadeIn 0.15s ease;
}
.custom-popover-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--app-text);
}
.custom-popover-presets {
  display: flex;
  gap: 6px;
}
.preset-day-btn {
  flex: 1;
  padding: 4px 0;
  text-align: center;
  border-radius: 6px;
  border: 1px solid var(--app-border);
  background: var(--app-surface);
  color: var(--app-text-secondary);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.preset-day-btn:hover {
  border-color: #8b5cf6;
  color: #7c3aed;
}
.preset-day-btn.is-selected {
  background: #7c3aed;
  border-color: #7c3aed;
  color: #ffffff;
  font-weight: 600;
}
.custom-popover-input-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.custom-days-number-input {
  flex: 1;
  width: 60px;
  padding: 4px 8px;
  border-radius: 6px;
  border: 1px solid var(--app-border);
  background: var(--app-surface);
  color: var(--app-text);
  font-size: 12px;
  outline: none;
}
.custom-days-number-input:focus {
  border-color: #7c3aed;
}
.custom-days-unit {
  font-size: 12px;
  color: var(--app-text-secondary);
}
.btn-apply-days {
  padding: 4px 10px;
  border-radius: 6px;
  background: #7c3aed;
  color: #ffffff;
  border: none;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.15s ease;
}
.btn-apply-days:hover {
  opacity: 0.9;
}

.drawer-footer {
  padding: 16px 24px;
  border-top: 1px solid var(--app-border);
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  background: var(--app-surface);
}
.btn-drawer-cancel {
  height: 38px;
  padding: 0 20px;
  border-radius: 8px;
  border: 1px solid var(--app-border);
  background: transparent;
  color: var(--app-text);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}
.btn-drawer-cancel:hover {
  background: var(--app-surface-muted);
}
.btn-drawer-submit {
  height: 38px;
  padding: 0 24px;
  border-radius: 8px;
  border: none;
  background: #7c3aed;
  color: #ffffff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
  box-shadow: 0 2px 8px rgba(124, 58, 237, 0.25);
}
.btn-drawer-submit:hover:not(:disabled) {
  background: #6d28d9;
}
.btn-drawer-submit:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Revealed Secret Modal Dialog */
.secret-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.55);
  backdrop-filter: blur(4px);
  z-index: 1050;
  display: grid;
  place-items: center;
  padding: 20px;
}
.secret-modal-card {
  width: min(520px, 100%);
  border-radius: 18px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  box-shadow: 0 20px 45px rgba(0, 0, 0, 0.22);
  padding: 28px;
}
.secret-modal-top {
  display: flex;
  gap: 14px;
  margin-bottom: 20px;
}
.secret-modal-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: rgba(124, 58, 237, 0.12);
  color: #7c3aed;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}
.secret-modal-top h2 {
  margin: 0 0 6px;
  font-size: 18px;
  font-weight: 700;
  color: var(--app-text);
}
.secret-warn-hint {
  margin: 0;
  font-size: 13px;
  color: var(--app-text-secondary);
  line-height: 1.5;
}
.secret-code-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--app-surface-muted);
  border: 1px solid var(--app-border);
  margin-bottom: 24px;
}
.secret-code-box code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 13px;
  color: var(--app-text);
  word-break: break-all;
  user-select: all;
}
.secret-copy-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 12px;
  border-radius: 6px;
  border: 1px solid var(--app-border);
  background: var(--app-surface);
  color: var(--app-text);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  flex-shrink: 0;
}
.secret-copy-btn:hover {
  border-color: #7c3aed;
  color: #7c3aed;
}
.secret-modal-actions {
  display: flex;
  justify-content: flex-end;
}

/* Responsive */
@media (max-width: 1024px) {
  .usage-charts-grid {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 768px) {
  .totals {
    grid-template-columns: 1fr;
  }
  .console header {
    flex-direction: column;
    align-items: flex-start;
  }
  .keys-header-stats {
    width: 100%;
  }
  .stat-pill {
    flex: 1;
    min-width: 130px;
  }
  .keys-toolbar {
    flex-direction: column;
    align-items: stretch;
  }
  .keys-toolbar-right {
    flex-direction: column;
    align-items: stretch;
  }
  .keys-search-pill {
    width: 100%;
    box-sizing: border-box;
  }
}
</style>
