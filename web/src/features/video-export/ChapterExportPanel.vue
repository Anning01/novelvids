<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { Download, LoaderCircle, RefreshCw, Sparkles } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import { API_BASE, authHeaders } from '@/api'
import { useAuthStore } from '@/features/auth/authStore'
import { appConfirm } from '@/shared/confirmDialog'
import { downloadFile } from '@/shared/downloadFile'
import { tr } from '@/i18n'
import { exportApi, type ChapterExport } from './api'

const props = defineProps<{ chapterId: number }>()
const auth = useAuthStore()
const canWrite = computed(() => !auth.enabled || auth.isSuperAdmin || ['admin', 'creator'].includes(auth.role || ''))
const exports = ref<ChapterExport[]>([])
const models = ref<Array<{ id: number; name: string }>>([])
const modelId = ref(0)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
let generation = 0
let alive = true
let timer: ReturnType<typeof setInterval> | undefined
const scope = computed(() => `${props.chapterId}:${auth.activeTeamId}:${auth.user?.id}`)
const active = computed(() => exports.value.some(row => [1, 2, 6].includes(row.status || 0) || row.stage === 'billing_pending'))

function status(row: ChapterExport) {
  if (row.stage === 'review_closed') return row.status === 5 ? tr('后续步骤已停止，已人工核对') : tr('已人工核对')
  if (row.stage === 'needs_review') return tr('需要核对')
  if (row.stage === 'billing_pending') return tr('用量正在结算')
  if (row.status === 5) return tr('后续步骤已停止')
  if (row.status === 4) return tr('导出失败')
  if (row.status === 3) return tr('已完成')
  if (row.stage === 'saving_result') return tr('正在保存高清成片')
  return row.parent_export_id ? tr('画质增强中') : tr('正在准备原片')
}

async function load(quiet = false) {
  if (!props.chapterId) return
  const version = ++generation
  const currentScope = scope.value
  if (!quiet) loading.value = true
  try {
    const [history, available] = await Promise.all([exportApi.list(props.chapterId), exportApi.models()])
    if (!alive || version !== generation || currentScope !== scope.value) return
    exports.value = history.data
    models.value = available.data
    if (!models.value.some(model => model.id === modelId.value)) modelId.value = models.value[0]?.id || 0
    error.value = ''
  } catch (caught) {
    if (alive && version === generation) error.value = (caught as Error).message
  } finally { if (alive && version === generation) loading.value = false }
}

async function prepare() {
  const currentScope = scope.value
  busy.value = true
  error.value = ''
  try {
    await exportApi.prepare(props.chapterId)
    if (currentScope === scope.value) await load(true)
  } catch (caught) { if (currentScope === scope.value) error.value = (caught as Error).message }
  finally { busy.value = false }
}

async function enhance(row: ChapterExport) {
  if (busy.value || !modelId.value) return
  const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null
  const currentScope = scope.value
  const selectedModel = modelId.value
  busy.value = true
  error.value = ''
  try {
    const quote = (await exportApi.quote(row.id, selectedModel)).data
    const confirmed = await appConfirm({ title: tr('确认生成1080p高清版'), tone: 'neutral',
      message: quote.reused_export_id ? tr('此版本已有高清结果，将直接复用，不产生新增增强费用。')
        : tr('本次预计 {p0} 元，保持原片帧率。增强会产生费用，原片继续保留。', { p0: quote.amount }),
      confirmLabel: quote.reused_export_id ? tr('使用已有高清版') : tr('确认增强并计费'),
    })
    if (!confirmed || currentScope !== scope.value || modelId.value !== selectedModel) return
    await exportApi.enhance(row.id, selectedModel, quote)
    if (currentScope === scope.value) await load(true)
  } catch (caught) { if (currentScope === scope.value) error.value = (caught as Error).message }
  finally {
    busy.value = false
    await nextTick()
    if (alive && currentScope === scope.value && trigger?.isConnected) trigger.focus()
  }
}

async function download(row: ChapterExport, source: boolean) {
  try {
    await downloadFile(`${API_BASE}/video/exports/${row.id}/download${source ? '?source=true' : ''}`, `chapter-${row.chapter_id}-export-${row.id}-${source ? 'source' : '1080p'}.mp4`, authHeaders())
  } catch (caught) { error.value = (caught as Error).message }
}
function focus() { if (document.visibilityState !== 'hidden') void load(true) }
watch(scope, () => { generation++; exports.value = []; error.value = ''; void load() })
onMounted(() => {
  void load()
  window.addEventListener('focus', focus)
  timer = setInterval(() => { if (active.value && document.visibilityState !== 'hidden') void load(true) }, 5000)
})
onUnmounted(() => { alive = false; generation++; clearInterval(timer); window.removeEventListener('focus', focus) })
</script>

<template>
  <section class="chapter-exports" :aria-label="tr('高清成片')">
    <header><div><strong>{{ tr('高清成片') }}</strong><p>{{ tr('先准备本集原片，确认后再付费增强。原片与高清版分别保留。') }}</p></div>
      <div class="export-actions">
        <AppButton size="sm" variant="ghost" :aria-label="tr('刷新导出记录')" @click="load()"><RefreshCw :size="16" /></AppButton>
        <AppButton v-if="canWrite" size="sm" variant="secondary" :disabled="busy || loading || !chapterId" @click="prepare"><LoaderCircle v-if="busy" class="spin" :size="15" />{{ tr('准备当前原片') }}</AppButton>
      </div>
    </header>
    <p v-if="error" role="alert" class="export-error">{{ error }}</p>
    <p v-if="loading && !exports.length" role="status">{{ tr('正在读取导出记录') }}</p>
    <p v-else-if="!exports.length" class="export-empty">{{ tr('尚无导出版本。只有本集全部镜头的视频就绪后才能准备原片。') }}</p>
    <label v-if="canWrite && exports.some(row => row.source_sha256 && !row.parent_export_id)" class="export-model">{{ tr('画质增强服务') }}
      <select v-model.number="modelId" :disabled="busy"><option :value="0">{{ tr('请选择增强服务') }}</option><option v-for="model in models" :key="model.id" :value="model.id">{{ model.name }}</option></select>
      <small v-if="!models.length">{{ tr('请在设置中配置并启用成片画质增强服务。') }}</small>
    </label>
    <ol class="export-list"><li v-for="row in exports" :key="row.id">
      <div class="export-description"><strong>{{ row.parent_export_id ? tr('1080p高清版') : tr('原片版本') }} · #{{ row.id }}</strong>
        <small v-if="row.selection_current === false">{{ tr('当前镜头选择已更新，此版本保留原内容。') }}</small>
        <span role="status"><LoaderCircle v-if="[1, 2, 6].includes(row.status || 0)" class="spin" :size="14" />{{ status(row) }}</span>
        <small v-if="row.source_probe.width">{{ tr('原片') }} {{ row.source_probe.width }}×{{ row.source_probe.height }} · {{ Number(row.source_probe.duration).toFixed(2) }}s · {{ row.source_probe.fps }}fps</small>
        <small v-if="row.parent_export_id && row.output_probe.width">{{ tr('高清版') }} {{ row.output_probe.width }}×{{ row.output_probe.height }} · {{ row.output_probe.fps }}fps</small>
        <p v-if="row.error" class="export-error">{{ row.error }}</p>
      </div>
      <div class="export-actions">
        <AppButton v-if="row.source_url" variant="ghost" size="sm" @click="download(row, true)"><Download :size="15" />{{ tr('下载原片') }}</AppButton>
        <AppButton v-if="row.parent_export_id && row.url && row.status !== 5" variant="secondary" size="sm" @click="download(row, false)"><Download :size="15" />{{ tr('下载高清版') }}</AppButton>
        <AppButton v-if="canWrite && !row.parent_export_id && row.status === 3" variant="primary" size="sm" :disabled="busy || !modelId" @click="enhance(row)"><Sparkles :size="15" />{{ tr('增强到1080p') }}</AppButton>
      </div>
    </li></ol>
  </section>
</template>

<style scoped>
.chapter-exports{background:var(--app-surface);color:var(--app-text);border:1px solid var(--app-border);border-radius:16px;padding:18px;margin:16px 0}
header,.export-list li{display:flex;align-items:center;justify-content:space-between;gap:16px}header p,.export-empty,.export-description small,.export-model small{color:var(--app-text-muted);font-size:13px;margin:6px 0}
.export-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.export-model{display:flex;gap:10px;align-items:center;margin:16px 0;flex-wrap:wrap;font-size:13px}
select{background:var(--app-surface-muted);color:var(--app-text);border:1px solid var(--app-border);border-radius:8px;padding:9px;max-width:100%}select:hover{background:var(--app-surface-hover)}select:focus-visible{outline:2px solid var(--app-accent);outline-offset:2px}select:disabled{opacity:.55}
.export-list{padding:0;margin:12px 0 0;list-style:none}.export-list li{padding:14px 0;border-top:1px solid var(--app-border)}.export-description{display:flex;flex-direction:column;gap:5px;min-width:0}.export-description span{display:flex;align-items:center;gap:6px;color:var(--app-text-secondary);font-size:13px}.export-error{color:var(--creation-danger);overflow-wrap:anywhere}.spin{animation:export-spin 1s linear infinite}@keyframes export-spin{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){.spin{animation:none}}@media(max-width:700px){header,.export-list li{align-items:flex-start;flex-direction:column}.export-actions{width:100%}}
.chapter-exports :deep(.app-button--secondary){background:var(--app-surface-muted);color:var(--app-text-secondary);box-shadow:inset 0 0 0 1px var(--app-border)}.chapter-exports :deep(.app-button--secondary:hover:not(:disabled)){background:var(--app-surface-hover);color:var(--app-text)}.chapter-exports :deep(.app-button--ghost:hover:not(:disabled)){background:var(--app-accent-soft);color:var(--app-accent)}
</style>
