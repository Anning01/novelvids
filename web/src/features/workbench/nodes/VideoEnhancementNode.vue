<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Download, LoaderCircle, RefreshCw, Settings2, SlidersHorizontal, Sparkles } from 'lucide-vue-next'
import { API_BASE, authHeaders } from '@/api'
import { useAuthStore } from '@/features/auth/authStore'
import { exportApi, type ChapterExport, type EnhancementModel } from '@/features/video-export/api'
import { appConfirm } from '@/shared/confirmDialog'
import { downloadFile, fetchFileBlob } from '@/shared/downloadFile'
import { tr } from '@/i18n'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
import WorkbenchVideoMedia from '../components/WorkbenchVideoMedia.vue'
import WorkbenchSelect from '../components/WorkbenchSelect.vue'
import { enhancementInput } from '../graph/enhancementInput'
import { registerWorkbenchNodeRun } from '../run/nodeRunRegistry'
import { useWorkbenchStore } from '../store/workbenchStore'

const props = defineProps<NodeProps>()
const store = useWorkbenchStore()
const auth = useAuthStore()
const data = computed(() => store.nodeByKey(props.id)?.data || props.data)
const scope = computed(() => `${store.chapterId}:${auth.activeTeamId}:${auth.user?.id}:${props.id}`)
const canWrite = computed(() => !auth.enabled || auth.isSuperAdmin || ['admin', 'creator'].includes(auth.role || ''))
const input = computed(() => enhancementInput(props.id, store.nodes, store.edges))
const submitted = computed(() => Boolean(data.value.export_id))
const models = ref<EnhancementModel[]>([])
const row = ref<ChapterExport | null>(null)
const requesting = ref(false)
const error = ref('')
const mediaUrl = ref('')
const previewLoading = ref(false)
const selectedModel = computed(() => Number(data.value.model_id) || models.value[0]?.id || 0)
const resolution = computed(() => String(data.value.resolution || '1080p'))
const model = computed(() => models.value.find(item => item.id === selectedModel.value))
const resolutions = computed(() => model.value?.resolutions || [])
const target = computed(() => resolutions.value.find(item => item.value === resolution.value))
const resolutionOptions = computed(() => (model.value?.supported_resolutions || resolutions.value).map(item => {
  const reason = input.value?.shortSide && input.value.shortSide >= item.short_side
    ? tr('不高于原片') : !resolutions.value.some(enabled => enabled.value === item.value) ? tr('服务未启用') : ''
  return { value: item.value, label: item.value.toUpperCase(), description: reason, disabled: Boolean(reason) }
}))
const hasUnconfiguredTargets = computed(() => model.value?.supported_resolutions?.some(item => !resolutions.value.some(enabled => enabled.value === item.value)))
const modelOptions = computed(() => models.value.map(item => ({ value: String(item.id), label: item.name })))
const active = computed(() => Boolean(row.value && ([1, 2, 6].includes(row.value.status || 0) || row.value.stage === 'billing_pending')))
const busy = computed(() => requesting.value || active.value)
const title = computed(() => `${tr('视频')} · ${String(row.value?.recipe.resolution || resolution.value).toUpperCase()}`)
const displayedRatio = computed(() => {
  const probe = row.value?.output_probe.width ? row.value.output_probe : row.value?.source_probe
  return probe?.width && probe.height ? `${probe.width}:${probe.height}` : input.value?.ratio || '16:9'
})
const locked = computed(() => busy.value || submitted.value || !canWrite.value)
const stageLabel = computed(() => row.value?.stage === 'needs_review' ? tr('需要核对')
  : row.value?.stage === 'billing_pending' ? tr('用量正在结算') : row.value?.status === 3 ? tr('已完成') : '')
const disabledReason = computed(() => {
  if (!canWrite.value) return tr('当前账号仅可查看')
  if (submitted.value) return tr('此视频已锁定，请重新拉线创建新视频')
  if (!input.value) return tr('请连接已生成成功的视频')
  if (!model.value) return tr('请在设置中配置并启用视频画质增强服务。')
  if (model.value.input_short_side_max && input.value.shortSide > model.value.input_short_side_max) return tr('所选服务不支持当前视频尺寸')
  if (!target.value) return tr('请在设置中启用所选清晰度')
  if (input.value.shortSide >= target.value.short_side) return tr('请选择高于原片的清晰度')
  return ''
})
const canRun = computed(() => !busy.value && !disabledReason.value)
let alive = true
let refreshingScope = ''
let previewScope = ''
let previewId = 0
let timer: ReturnType<typeof setInterval> | undefined

function patch(value: Record<string, unknown>) { store.updateManualNodeData(props.id, value); store.persistLayout() }
function clearPreview() {
  if (mediaUrl.value) URL.revokeObjectURL(mediaUrl.value)
  mediaUrl.value = ''; previewId = 0
}
async function showResult(result: ChapterExport, currentScope: string) {
  if (!result.url || result.status !== 3 || previewId === result.id || previewLoading.value && previewScope === currentScope) return
  previewScope = currentScope
  previewLoading.value = true
  try {
    const blob = await fetchFileBlob(`${API_BASE}/video/exports/${result.id}/download`, authHeaders())
    if (!alive || scope.value !== currentScope) return
    clearPreview()
    mediaUrl.value = URL.createObjectURL(blob); previewId = result.id
  } catch (caught) { if (alive && scope.value === currentScope) error.value = (caught as Error).message }
  finally { if (scope.value === currentScope) previewLoading.value = false }
}
async function refresh() {
  const id = Number(data.value.export_id)
  const currentScope = scope.value
  if (!id || refreshingScope === currentScope) return
  refreshingScope = currentScope
  try {
    const result = (await exportApi.get(id)).data
    if (!alive || scope.value !== currentScope) return
    row.value = result
    patch({ enhancement_result: result })
    await showResult(result, currentScope)
  } catch (caught) { if (alive && scope.value === currentScope) error.value = (caught as Error).message }
  finally { if (refreshingScope === currentScope) refreshingScope = '' }
}
async function initialize() {
  const currentScope = scope.value
  try {
    const response = await exportApi.models()
    if (!alive || scope.value !== currentScope) return
    models.value = response.data
    await refresh()
  } catch (caught) { if (alive && scope.value === currentScope) error.value = (caught as Error).message }
}
async function run() {
  if (!canRun.value || !input.value) return
  const source = { ...input.value }
  const currentScope = scope.value
  const configId = selectedModel.value
  const output = resolution.value
  const unchanged = () => alive && scope.value === currentScope && input.value?.key === source.key
    && selectedModel.value === configId && resolution.value === output
  requesting.value = true; error.value = ''
  try {
    const sourceId = source.exportId || (await exportApi.prepareVideo(source.videoId!)).data.export_id
    let original = (await exportApi.get(sourceId)).data
    while (unchanged() && [1, 2, 6].includes(original.status || 0)) {
      await new Promise(resolve => setTimeout(resolve, 1500))
      if (!unchanged()) return
      original = (await exportApi.get(sourceId)).data
    }
    if (!unchanged()) return
    if (original.status !== 3) throw new Error(original.error || tr('原片准备失败'))
    const quote = (await exportApi.quote(sourceId, configId, output)).data
    if (!unchanged()) return
    const confirmed = await appConfirm({ title: tr('确认增强到 {p0}', { p0: output.toUpperCase() }), tone: 'neutral',
      message: quote.reused_export_id ? tr('此版本已有高清结果，将直接复用，不产生新增增强费用。')
        : tr('本次预计 {p0} 元，保持原片帧率。增强会产生费用，原片继续保留。', { p0: quote.amount }),
      confirmLabel: quote.reused_export_id ? tr('使用已有高清版') : tr('确认增强并计费'),
    })
    if (!confirmed || !unchanged()) return
    const result = (await exportApi.enhance(sourceId, configId, quote, output)).data
    if (!alive || scope.value !== currentScope) return
    patch({ export_id: result.export_id, source_export_id: sourceId, source_title: source.title,
      model_id: configId, resolution: output })
    await refresh()
  } catch (caught) { if (alive && scope.value === currentScope) error.value = (caught as Error).message }
  finally { requesting.value = false }
}
async function download() {
  if (!row.value?.url) return
  try { await downloadFile(`${API_BASE}/video/exports/${row.value.id}/download`, `video-${row.value.id}-${resolution.value}.mp4`, authHeaders()) }
  catch (caught) { error.value = (caught as Error).message }
}
registerWorkbenchNodeRun(props.id, { enabled: canRun, run })
watch(scope, () => { row.value = null; models.value = []; error.value = ''; clearPreview(); void initialize() })
onMounted(() => { void initialize(); timer = setInterval(() => { if (active.value && document.visibilityState !== 'hidden') void refresh() }, 5000) })
onUnmounted(() => { alive = false; clearInterval(timer); clearPreview() })
</script>

<template>
  <WorkbenchNodeFrame v-bind="props" class="viral-workbench-surface-theme" :data="{ ...data, kind: 'video_enhancement', title, body_flush: true, body_draggable: true, floating_header: true, borderless_media: true }">
    <template #meta>
      <span v-if="row?.output_probe.width">{{ row.output_probe.width }} × {{ row.output_probe.height }}</span>
      <span v-if="stageLabel" class="enhanced-video-status" role="status">{{ stageLabel }}</span>
    </template>
    <template #toolbar-actions>
      <WorkbenchSelect v-if="!submitted && models.length > 1" class="enhanced-video-service" :model-value="String(selectedModel)" :options="modelOptions" :label="tr('画质增强服务')" :fallback-icon="SlidersHorizontal" icon-only :disabled="locked" @update:model-value="patch({ model_id: Number($event) })" />
      <a v-if="!submitted && hasUnconfiguredTargets && auth.canAccessSettings" class="enhanced-video-settings" href="#/settings" :aria-label="tr('启用更多清晰度')" :title="tr('启用更多清晰度')"><Settings2 :size="16" aria-hidden="true" /></a>
      <button v-if="row?.url" type="button" :aria-label="tr('下载视频')" @click="download"><Download :size="16" /></button>
      <button v-if="row" type="button" :aria-label="tr('刷新状态')" @click="refresh"><RefreshCw :size="16" /></button>
    </template>
    <div class="enhanced-video-card">
      <WorkbenchVideoMedia :src="mediaUrl" :title="title" :ratio="displayedRatio" :running="submitted || previewLoading" :failed="row?.status === 4 || row?.status === 5"
        :error="row?.error || error" empty-label="" :running-label="tr('画质增强中')" />
      <div v-if="!submitted" class="enhanced-video-dock nodrag nopan nowheel" role="group" :aria-label="tr('视频增强操作')" @pointerdown.stop @click.stop>
        <WorkbenchSelect class="enhanced-video-resolution" :model-value="resolution" :options="resolutionOptions" :label="tr('目标清晰度')" :placeholder="resolution.toUpperCase()" :disabled="locked" @update:model-value="patch({ resolution: $event })" />
        <button class="enhanced-video-run" type="button" :aria-label="tr('增强到 {p0}', { p0: resolution.toUpperCase() })" :title="disabledReason || tr('确认费用后增强')" :disabled="!canRun" :aria-busy="busy" @click="run">
          <LoaderCircle v-if="busy" class="enhanced-video-spinner" :size="16" aria-hidden="true" /><Sparkles v-else :size="16" aria-hidden="true" />
          {{ busy ? tr('准备中') : tr('增强') }}
        </button>
      </div>
      <p v-if="!submitted && (error || disabledReason)" class="enhanced-video-notice" :class="{ 'is-error': Boolean(error) }" :role="error ? 'alert' : 'status'">
        {{ error || disabledReason }}
      </p>
      <p v-if="row && error" class="enhanced-video-notice is-error" role="alert">{{ error }}</p>
    </div>
  </WorkbenchNodeFrame>
</template>

<style scoped>
.enhanced-video-card{position:relative;width:100%;min-width:0;color:var(--vf-text-primary,#eee9e2);background:var(--vf-bg-canvas,#151412);border-radius:16px}
.enhanced-video-card :deep(.workbench-video-media){margin:0;border-radius:16px;overflow:hidden}
.enhanced-video-card :deep(.workbench-media-placeholder){min-height:0;border-radius:16px;background:var(--vf-bg-canvas,#151412);color:var(--vf-text-secondary,#c7bdb4)}
.enhanced-video-card :deep(.workbench-media-placeholder.is-generating .workbench-media-placeholder__state>span){display:none}
.enhanced-video-card :deep(.workbench-media-placeholder.is-failed){color:var(--vf-danger,var(--creation-danger))}
.enhanced-video-dock{position:absolute;top:50%;left:50%;display:flex;gap:10px;align-items:center;max-width:calc(100% - 24px);padding:0;border:0;background:transparent;transform:translate(-50%,-50%);z-index:6}
.enhanced-video-resolution{width:104px;flex:none}
.enhanced-video-resolution :deep(.workbench-select__trigger){height:40px!important;border:0!important;background:transparent!important;color:var(--vf-text-primary,#eee9e2)!important;padding:6px 8px!important;font-size:14px}
.enhanced-video-resolution :deep(.workbench-select__content){width:230px;left:50%;transform:translateX(-50%)}
.enhanced-video-resolution :deep(.workbench-select__trigger:disabled){opacity:.55;cursor:default}
.enhanced-video-run{display:inline-flex;min-width:76px;height:40px;gap:7px;align-items:center;justify-content:center;padding:6px 10px;border:0;border-radius:7px;background:transparent;color:var(--vf-accent,#a995ff);font:inherit;font-size:14px;font-weight:600;cursor:pointer;white-space:nowrap}
.enhanced-video-run:hover:not(:disabled){background:var(--vf-bg-muted,#2a2622)}.enhanced-video-run:disabled{opacity:.45;cursor:not-allowed}.enhanced-video-run:focus-visible,.enhanced-video-settings:focus-visible{outline:2px solid var(--vf-accent,#a995ff);outline-offset:3px}
.enhanced-video-notice{position:absolute;inset:12px 16px auto;margin:0;color:var(--vf-text-secondary,var(--app-text-secondary));text-align:center;font-size:12px;line-height:1.5;overflow-wrap:anywhere;pointer-events:none}.enhanced-video-notice.is-error{color:var(--vf-danger,var(--creation-danger))}
.enhanced-video-status{color:var(--vf-text-secondary,var(--app-text-secondary));font-size:11px}.enhanced-video-service{width:32px}.enhanced-video-service :deep(.workbench-select__content){min-width:200px}.enhanced-video-settings{display:inline-flex;width:32px;height:32px;align-items:center;justify-content:center;color:inherit;border-radius:6px}.enhanced-video-settings:hover{background:var(--vf-bg-muted,var(--app-surface-hover))}
.enhanced-video-spinner{animation:enhancement-spin 1s linear infinite}@keyframes enhancement-spin{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){.enhanced-video-spinner{animation:none}}
</style>
