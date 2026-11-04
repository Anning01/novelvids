<script setup lang="ts">
import { computed, ref, toRef, watch } from 'vue'
import { ArrowRight, Check, ChevronDown, CircleCheck, Download, History, Info, LoaderCircle, Play, Sparkles, X } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import AppSelect from '@/components/AppSelect.vue'
import VideoThumbnail from '@/components/VideoThumbnail.vue'
import { mediaUrl } from '@/api'
import { tr } from '@/i18n'
import { money } from '@/features/billing/recordDisplay'
import { videoCoverUrl } from '@/features/workbench/graph/videoMedia'
import type { Video } from '@/types'
import type { ChapterExport } from './api'
import { useVideoEnhancement } from './useVideoEnhancement'

const props = defineProps<{ video: Video; visible: boolean; titleId: string; sceneSequence?: number; pixelSize?: { width: number; height: number } | null }>()
const emit = defineEmits<{ close: []; applied: [id: number] }>()
const {
  rows, models, modelId, resolution, source, run, model, size, shortSide, resolutions, target, locked,
  loadingModels, loadingHistory, preparing, submitting, quoting, uncertain, submittedId, quote, error, quoteError,
  canWrite, resultVideo, sourceReady, submittedQuote, fetchQuote, refresh, submit, apply, restoreOriginal, download,
} = useVideoEnhancement(toRef(props, 'video'), toRef(props, 'visible'), id => emit('applied', id), toRef(props, 'pixelSize'))
const playing = ref(false), playbackError = ref(false)
const preview = computed(() => resultVideo.value || props.video)
watch(() => props.visible, value => { if (!value) playing.value = false })
watch(() => preview.value.id, () => { playing.value = false; playbackError.value = false })
const probe = computed(() => resultVideo.value && run.value?.output_probe.width ? run.value.output_probe : source.value?.source_probe)
const displayedSize = computed(() => probe.value?.width && probe.value.height ? `${probe.value.width} × ${probe.value.height}`
  : (size.value || props.pixelSize) ? `${(size.value || props.pixelSize)!.width} × ${(size.value || props.pixelSize)!.height}` : tr('尺寸待核对'))
const resolutionLabel = computed(() => String(run.value?.recipe.resolution || resolution.value).toUpperCase())
const phase = computed(() => {
  if (uncertain.value || run.value?.stage === 'needs_review') return 'review'
  if (run.value?.stage === 'billing_pending') return 'processing'
  if (run.value?.status === 3 && run.value.url) return 'completed'
  if (run.value && [4, 5].includes(run.value.status || 0)) return 'failed'
  if (run.value || submittedId.value || submitting.value) return 'processing'
  if (error.value || (source.value && [4, 5].includes(source.value.status || 0))) return 'error'
  if (!loadingModels.value && !models.value.length) return 'unavailable'
  if (!loadingModels.value && models.value.length && !resolutions.value.some(item => !item.disabled)) return 'max'
  if (model.value?.input_short_side_max && shortSide.value > model.value.input_short_side_max) return 'unsupported'
  if (loadingHistory.value || loadingModels.value || preparing.value || !sourceReady.value || quoting.value || !quote.value) return 'checking'
  return 'ready'
})
const statusText = computed(() => {
  if (phase.value === 'review') return tr('提交结果待核对')
  if (phase.value === 'completed') return run.value?.applied_to_scene ? tr('已设为当前视频') : tr('高清版已完成')
  if (phase.value === 'failed') return tr('增强未完成')
  if (phase.value === 'error') return tr('暂时无法继续')
  if (phase.value === 'unavailable') return tr('尚未配置增强服务')
  if (phase.value === 'max') return tr('没有更高的可用清晰度')
  if (phase.value === 'unsupported') return tr('所选服务不支持当前视频尺寸')
  if (phase.value === 'processing') return run.value?.stage === 'billing_pending' ? tr('用量正在结算') : run.value?.stage === 'saving_result' ? tr('正在保存高清成片') : tr('画质增强中')
  return tr('正在核对视频与费用')
})
const statusDetail = computed(() => {
  if (phase.value === 'review') return tr('请勿重复提交，可关闭弹窗继续创作。')
  if (phase.value === 'completed') return tr('原片保留，可在版本记录中找回。')
  if (phase.value === 'processing') return tr('可关闭弹窗继续创作，完成后自动更新。')
  if (phase.value === 'unavailable') return tr('请联系团队管理员添加可用服务。')
  if (phase.value === 'max') return tr('只能选择高于当前视频的清晰度。')
  if (phase.value === 'unsupported') return tr('请选择支持当前视频尺寸的增强服务。')
  if (phase.value === 'failed') return run.value?.error || tr('请查看任务状态，原视频继续保留。')
  return error.value || source.value?.error || tr('视频仍可预览，确认前不会提交付费增强。')
})
const primaryLabel = computed(() => phase.value === 'completed' ? (run.value?.applied_to_scene ? tr('下载高清版') : tr('使用此版本'))
  : ['processing', 'failed', 'review'].includes(phase.value) ? tr('返回创作')
  : phase.value === 'error' ? tr('重新读取') : phase.value === 'ready' ? quote.value?.reused_export_id ? tr('使用已有高清版') : tr('确认增强到 {p0}', { p0: resolutionLabel.value })
  : phase.value === 'unavailable' ? tr('暂无可用服务') : phase.value === 'max' ? tr('无需增强') : phase.value === 'unsupported' ? tr('当前尺寸不可用') : tr('正在核对…'))
const amount = computed(() => {
  const value = locked.value ? submittedQuote.value : quote.value
  return value ? money(Number(value.amount), value.currency) : '—'
})
const modelOptions = computed(() => models.value.map(item => ({ value: String(item.id), label: item.name })))
function historyLabel(row: ChapterExport) {
  return row.parent_export_id ? tr('{p0} 高清版', { p0: String(row.recipe.resolution || '').toUpperCase() }) : tr('原视频')
}
async function primary() {
  if (phase.value === 'ready') await submit()
  else if (phase.value === 'completed' && run.value) {
    if (run.value.applied_to_scene) await download(run.value)
    else await apply(run.value)
  } else if (phase.value === 'error') {
    if (quoteError.value) await fetchQuote()
    else await refresh()
  } else emit('close')
}
function moveTarget(event: KeyboardEvent) {
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return
  const controls = [...(event.currentTarget as HTMLElement).querySelectorAll<HTMLButtonElement>('button:not(:disabled)')]
  const index = controls.indexOf(document.activeElement as HTMLButtonElement)
  if (index < 0) return
  event.preventDefault()
  const next = controls[(index + (['ArrowLeft', 'ArrowUp'].includes(event.key) ? -1 : 1) + controls.length) % controls.length]
  next?.focus(); next?.click()
}
</script>

<template>
  <header class="enhancement-header">
    <div class="enhancement-title"><span class="enhancement-icon"><Sparkles :size="20" aria-hidden="true" /></span><div><h2 :id="titleId">{{ tr('视频高清化') }}</h2><p>{{ sceneSequence ? tr('分镜 {p0}', { p0: sceneSequence }) : tr('当前视频') }}<span v-if="sceneSequence"> · {{ tr('当前视频') }}</span></p></div></div>
    <AppButton variant="ghost" icon-only size="sm" :aria-label="tr('关闭')" @click="emit('close')"><X :size="18" aria-hidden="true" /></AppButton>
  </header>
  <div class="enhancement-body">
    <div class="enhancement-source">
      <div class="enhancement-preview">
        <video v-if="playing" :key="preview.id" :src="mediaUrl(preview.url || '')" controls autoplay playsinline preload="metadata" :aria-label="tr('预览当前视频')" @error="playbackError = true" />
        <template v-else><VideoThumbnail :key="preview.id" :src="mediaUrl(preview.url || '')" :poster="mediaUrl(videoCoverUrl(preview))" fit="contain" /><button type="button" class="enhancement-play" :aria-label="tr('预览当前视频')" @click="playing = true"><span><Play :size="19" aria-hidden="true" /></span></button></template>
        <span v-if="!playing" class="enhancement-media-tag">{{ resultVideo ? resolutionLabel : tr('当前视频') }}</span>
      </div>
      <p v-if="playbackError" class="enhancement-media-error" role="alert">{{ tr('视频暂时无法播放，请稍后重试。') }}</p>
      <div class="enhancement-media-info"><div><strong>{{ resultVideo ? tr('{p0} 高清版', { p0: resolutionLabel }) : tr('原视频') }}</strong><p>{{ displayedSize }}<template v-if="probe?.duration"> · {{ Number(probe.duration).toFixed(2) }}s</template><template v-if="probe?.fps"> · {{ Number(probe.fps) }} fps</template></p></div><AppButton variant="ghost" icon-only size="sm" :aria-label="tr('下载当前版本')" @click="download(resultVideo && run ? run : undefined)"><Download :size="16" aria-hidden="true" /></AppButton></div>
      <p class="enhancement-source-note"><CircleCheck :size="14" aria-hidden="true" /><span>{{ tr('完成后自动替换当前视频') }}<br>{{ tr('原片保留，可在版本记录中找回。') }}</span></p>
    </div>
    <div class="enhancement-settings">
      <h3>{{ tr('目标清晰度') }}</h3>
      <div class="enhancement-resolutions" role="radiogroup" :aria-label="tr('目标清晰度')" :aria-busy="loadingModels" @keydown="moveTarget">
        <button v-for="item in resolutions" :key="item.value" type="button" :aria-label="item.value.toUpperCase()" :aria-checked="resolution === item.value" role="radio" :disabled="item.disabled || locked || !canWrite" :title="item.reason" @click="resolution = item.value"><span>{{ item.value.toUpperCase() }}<small v-if="item.reason">{{ item.reason }}</small></span><Check v-if="resolution === item.value" :size="14" aria-hidden="true" /></button>
        <span v-if="loadingModels && !resolutions.length" class="enhancement-skeleton">{{ tr('正在读取配置…') }}</span>
      </div>
      <p v-if="target && !target.disabled" class="enhancement-output"><ArrowRight :size="13" aria-hidden="true" />{{ tr('输出短边 {p0}px，保持比例与帧率', { p0: target.short_side }) }}</p>
      <p v-else-if="model?.input_short_side_max && shortSide > model.input_short_side_max" class="enhancement-output">{{ tr('所选服务不支持当前视频尺寸') }}</p>
      <div class="enhancement-service"><label>{{ tr('增强服务') }}</label><AppSelect v-model="modelId" :options="modelOptions" :ariaLabel="tr('增强服务')" density="compact" :disabled="locked || !canWrite || !models.length" /></div>
      <div v-if="phase !== 'ready'" class="enhancement-status" :class="{ 'is-success': phase === 'completed', 'is-error': ['error', 'failed', 'review'].includes(phase) }" :role="['error', 'failed', 'review'].includes(phase) ? 'alert' : 'status'">
        <CircleCheck v-if="phase === 'completed'" :size="16" aria-hidden="true" /><LoaderCircle v-else-if="['checking', 'processing'].includes(phase)" class="enhancement-spin" :size="16" aria-hidden="true" /><Info v-else :size="16" aria-hidden="true" /><div><strong>{{ statusText }}</strong><p>{{ statusDetail }}</p><AppButton v-if="phase === 'review'" variant="ghost" size="xs" @click="refresh">{{ tr('刷新状态') }}</AppButton></div>
      </div>
      <p v-if="error && !['error', 'review'].includes(phase)" class="enhancement-media-error" role="alert">{{ error }}</p>
    </div>
  </div>
  <details class="enhancement-history"><summary><span><History :size="14" aria-hidden="true" />{{ tr('版本记录') }}</span><span>{{ tr('{p0} 个版本', { p0: rows.length }) }}<ChevronDown :size="14" aria-hidden="true" /></span></summary>
    <div v-if="!rows.length" class="enhancement-history-empty">{{ loadingHistory ? tr('正在读取…') : tr('暂无版本记录') }}</div>
    <div v-for="row in rows" :key="row.id" class="enhancement-version"><div><strong>{{ historyLabel(row) }}</strong><small>{{ row.applied_to_scene ? tr('当前使用') : row.status === 3 ? tr('已完成') : row.status === 4 ? tr('增强未完成') : tr('处理中') }}</small></div><div><AppButton v-if="row.parent_export_id && row.status === 3 && !row.applied_to_scene && canWrite" variant="ghost" size="xs" :disabled="submitting" @click="apply(row)">{{ tr('使用此版本') }}</AppButton><AppButton v-if="!row.parent_export_id && phase === 'completed' && run?.applied_to_scene && canWrite" variant="ghost" size="xs" :disabled="submitting" @click="restoreOriginal">{{ tr('恢复原视频') }}</AppButton><AppButton v-if="row.url && row.status === 3" variant="ghost" icon-only size="sm" :aria-label="tr('下载{p0}', { p0: historyLabel(row) })" @click="download(row)"><Download :size="14" aria-hidden="true" /></AppButton></div></div>
  </details>
  <footer class="enhancement-footer"><div class="enhancement-cost"><p><span>{{ tr('预计费用') }}</span><strong>{{ phase === 'checking' ? tr('核对中') : amount }}</strong></p><small>{{ quote?.reused_export_id && phase === 'ready' ? tr('使用已有结果，不产生新增增强费用') : phase === 'ready' ? tr('确认后开始计费') : ['processing', 'completed', 'review', 'failed'].includes(phase) ? tr('实际费用以账单记录为准') : tr('获取有效报价后才可确认') }}</small></div>
    <AppButton class="enhancement-primary" variant="primary" :disabled="['checking', 'unavailable', 'max', 'unsupported'].includes(phase) || !canWrite || submitting" @click="primary"><Download v-if="phase === 'completed' && run?.applied_to_scene" :size="16" aria-hidden="true" /><ArrowRight v-else-if="['processing', 'review', 'failed'].includes(phase)" :size="16" aria-hidden="true" /><Sparkles v-else :size="16" aria-hidden="true" />{{ primaryLabel }}</AppButton>
  </footer>
</template>

<style scoped>
.enhancement-header { display:flex;align-items:center;justify-content:space-between;gap:16px;padding:23px 26px 21px; }
.enhancement-title { display:flex;align-items:center;gap:12px; }.enhancement-icon { display:grid;place-items:center;width:38px;height:38px;border:1px solid color-mix(in srgb,var(--app-accent) 22%,transparent);border-radius:11px;color:var(--app-accent);background:var(--app-accent-soft); }
h2 { margin:0;font-size:19px;line-height:1.4;font-weight:650; }.enhancement-title p { margin:3px 0 0;color:var(--app-text-secondary);font-size:12px; }
.enhancement-body { display:grid;grid-template-columns:minmax(0,1.22fr) minmax(0,1fr);gap:28px;padding:0 26px 24px; }.enhancement-source,.enhancement-settings { min-width:0; }
.enhancement-preview { position:relative;aspect-ratio:16/9;overflow:hidden;border-radius:11px;background:var(--app-surface-muted); }.enhancement-preview>video { display:block;width:100%;height:100%;object-fit:contain; }
.enhancement-play { position:absolute;inset:0;display:grid;place-items:center;width:100%;border:0;background:transparent;color:#fff;cursor:pointer; }.enhancement-play>span { display:grid;place-items:center;width:42px;height:42px;border:1px solid rgb(255 255 255 / 55%);border-radius:50%;background:rgb(18 20 20 / 60%); }.enhancement-play:hover>span { border-color:#fff;background:rgb(18 20 20 / 85%); }.enhancement-play:focus-visible { outline:3px solid var(--app-accent);outline-offset:-3px; }.enhancement-play svg { fill:currentColor;margin-left:3px; }
.enhancement-media-tag { position:absolute;top:10px;left:10px;padding:3px 7px;border-radius:5px;background:rgb(0 0 0 / 55%);color:#fff;font-size:11px;pointer-events:none; }
.enhancement-media-info { display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:11px; }.enhancement-media-info strong { font-size:13px;font-weight:550; }.enhancement-media-info p { margin:3px 0 0;color:var(--app-text-secondary);font-size:12px;font-variant-numeric:tabular-nums; }
.enhancement-source-note { display:flex;align-items:start;gap:7px;margin:19px 0 0;color:var(--app-text-secondary);font-size:12px;line-height:1.65; }.enhancement-source-note svg { flex-shrink:0;margin-top:3px;color:var(--creation-success); }
h3 { margin:0 0 12px;font-size:13px;font-weight:550; }.enhancement-resolutions { display:grid;grid-template-columns:1fr 1fr;gap:8px; }.enhancement-resolutions>button { display:flex;align-items:center;justify-content:space-between;gap:4px;min-height:54px;padding:9px 12px;border:1px solid var(--app-border);border-radius:9px;background:transparent;color:var(--app-text);text-align:left;font:inherit;font-size:14px;cursor:pointer; }.enhancement-resolutions>button>span { display:flex;flex-direction:column;gap:2px; }.enhancement-resolutions small { color:var(--app-text-secondary);font-size:10px; }.enhancement-resolutions>button:hover:not(:disabled) { background:var(--app-surface-hover);border-color:var(--app-border-strong); }.enhancement-resolutions>button[aria-checked=true] { color:var(--app-accent);background:var(--app-accent-soft);border-color:var(--app-accent); }.enhancement-resolutions>button:disabled { color:var(--app-text-secondary);background:var(--app-surface-muted);cursor:not-allowed;opacity:.65; }.enhancement-resolutions>button:focus-visible { outline:2px solid var(--app-accent);outline-offset:3px; }
.enhancement-output { display:flex;align-items:start;gap:5px;margin:9px 0 0;color:var(--app-text-secondary);font-size:11px;line-height:1.6; }.enhancement-output svg { flex-shrink:0;margin-top:2px; }
.enhancement-service { display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:20px;padding-top:16px;border-top:1px solid var(--app-border); }.enhancement-service label { color:var(--app-text-secondary);font-size:12px; }.enhancement-service :deep(.app-select) { width:170px;max-width:65%; }.enhancement-service :deep(.app-select__trigger) { min-height:34px;background:transparent;box-shadow:none;border-color:transparent; }
.enhancement-status { display:flex;align-items:start;gap:9px;margin-top:16px;padding:12px;border:1px solid var(--app-border);border-radius:9px;background:var(--app-surface-muted); }.enhancement-status>svg { flex-shrink:0;margin-top:2px;color:var(--app-accent); }.enhancement-status.is-success>svg { color:var(--creation-success); }.enhancement-status.is-error>svg { color:var(--creation-danger); }.enhancement-status strong { font-size:12px;font-weight:550; }.enhancement-status p { margin:4px 0 0;color:var(--app-text-secondary);font-size:11px;line-height:1.6;overflow-wrap:anywhere; }.enhancement-media-error { color:var(--creation-danger);font-size:12px; }.enhancement-skeleton { grid-column:1/-1;display:grid;min-height:116px;place-items:center;color:var(--app-text-secondary);border-radius:9px;background:var(--app-surface-muted);font-size:12px; }
.enhancement-history { margin:0 26px;border-top:1px solid var(--app-border); }.enhancement-history summary { display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:46px;padding:14px 0;list-style:none;color:var(--app-text-secondary);font-size:12px;cursor:pointer; }.enhancement-history summary::-webkit-details-marker { display:none; }.enhancement-history summary>span { display:flex;align-items:center;gap:7px; }.enhancement-history summary>span:last-child { color:var(--app-text-muted);font-size:11px; }.enhancement-history summary:focus-visible { outline:2px solid var(--app-accent);outline-offset:2px; }.enhancement-history[open] summary>span:last-child svg { transform:rotate(180deg); }.enhancement-history-empty { padding:0 0 16px;color:var(--app-text-secondary);font-size:12px; }.enhancement-version,.enhancement-version>div { display:flex;align-items:center;gap:8px; }.enhancement-version { justify-content:space-between;min-height:44px;padding:4px 0 8px; }.enhancement-version strong { font-size:12px;font-weight:500; }.enhancement-version small { color:var(--app-text-secondary);font-size:11px; }
.enhancement-footer { display:flex;align-items:center;justify-content:space-between;gap:20px;padding:18px 26px 22px;border-top:1px solid var(--app-border);background:color-mix(in srgb,var(--app-surface-muted) 35%,var(--app-surface)); }.enhancement-cost p { display:flex;align-items:baseline;gap:10px;margin:0; }.enhancement-cost p>span { color:var(--app-text-secondary);font-size:12px; }.enhancement-cost strong { font-size:22px;font-weight:600;line-height:1.2;font-variant-numeric:tabular-nums; }.enhancement-cost>small { display:block;margin-top:4px;color:var(--app-text-secondary);font-size:11px; }.enhancement-primary { min-width:174px;min-height:42px; }
.enhancement-spin { animation:enhancement-spin 1s linear infinite; }@keyframes enhancement-spin { to{transform:rotate(360deg)} }@media(prefers-reduced-motion:reduce){.enhancement-spin{animation:none}}
@media(max-width:660px){.enhancement-header{padding:19px 18px}.enhancement-body{padding:0 18px 18px;grid-template-columns:1fr;gap:23px}.enhancement-title{gap:10px}.enhancement-icon{width:34px;height:34px}.enhancement-resolutions{grid-template-columns:repeat(4,minmax(0,1fr));gap:6px}.enhancement-resolutions>button{padding:8px;font-size:12px}.enhancement-resolutions small{font-size:9px}.enhancement-history{margin:0 18px}.enhancement-footer{padding:16px 18px;gap:12px}.enhancement-primary{min-width:145px;padding-inline:10px}.enhancement-cost strong{font-size:19px}.enhancement-cost>small{max-width:150px}.enhancement-cost p{gap:6px}.enhancement-source-note{margin-top:12px}.enhancement-service{margin-top:16px;padding-top:10px}}
@media(max-width:660px){.enhancement-footer{align-items:stretch;flex-direction:column}.enhancement-primary{width:100%}.enhancement-cost p{justify-content:space-between}.enhancement-cost>small{max-width:none}}
</style>
