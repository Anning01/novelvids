<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { AlertCircle, Clock3, Image, Film, LoaderCircle, Maximize2 } from 'lucide-vue-next'
import ImageLightbox from '@/components/ImageLightbox.vue'
import { mediaUrl } from '@/api'
import { tr } from '@/i18n'
import { money } from '@/features/billing/recordDisplay'
import type { BillingRecord } from '@/types'

const props = withDefaults(defineProps<{
  kind: 'image' | 'video'
  name: string
  src?: string
  status?: number
  createdAt?: string | null
  finishedAt?: string | null
  preparing?: boolean
  error?: string
  model?: string
  resolution?: string
  aspectRatio: string
  prompt: string
  duration?: number
  requestedFormat?: string
  records?: BillingRecord[]
  estimatedCost?: string | null
  estimateCurrency?: string
  costError?: boolean
  showCosts?: boolean
}>(), { showCosts: true })
const now = ref(Date.now()), lightboxOpen = ref(false), dimensions = ref(''), loadedDuration = ref<number | null>(null)
const active = computed(() => Boolean(props.preparing || (props.status !== undefined && [1, 2, 6].includes(props.status))))
const title = computed(() => props.preparing ? tr('正在准备生成') : props.status === 1 || props.status === 6 ? tr('排队等待生成')
  : props.status === 2 ? tr(props.kind === 'image' ? '图片生成中' : '视频生成中')
    : tr(({ 3: '已完成', 4: '生成失败', 5: '已取消' } as Record<number, string>)[props.status || 0] || '等待生成'))
const records = computed(() => props.records || [])
const actualFormat = computed(() => props.src?.split(/[?#]/, 1)[0]?.match(/\.([a-z0-9]+)$/i)?.[1]?.toUpperCase().replace('JPG', 'JPEG') || '')
const actualCost = computed(() => {
  if (!records.value.length) return tr(props.costError ? '费用暂未同步' : '待结算')
  if (records.value.some(record => ['pending', 'review'].includes(record.settlement_status || ''))) return tr('待结算')
  if (records.value.some(record => record.usage.missing_usage || record.usage.accounting_needs_review)) return tr('费用待核对')
  const totals = new Map<string, number>()
  for (const record of records.value) totals.set(record.currency, (totals.get(record.currency) || 0) + record.cost)
  return [...totals].map(([currency, total]) => money(total, currency)).join(' + ')
})
const elapsedSeconds = computed(() => {
  const start = Date.parse(props.createdAt || '')
  const finish = active.value ? now.value : Date.parse(props.finishedAt || '')
  if (Number.isFinite(start) && Number.isFinite(finish)) return Math.max(0, Math.floor((finish - start) / 1000))
  const recorded = records.value.find(record => record.duration_seconds != null)?.duration_seconds
  return recorded != null && Number.isFinite(recorded) ? Math.max(0, Math.floor(recorded)) : null
})
const elapsed = computed(() => {
  const seconds = elapsedSeconds.value
  return seconds === null ? tr(active.value ? '正在同步计时信息' : '暂无耗时记录')
    : seconds < 60 ? tr('{p0} 秒', { p0: seconds }) : tr('{p0} 分 {p1} 秒', { p0: Math.floor(seconds / 60), p1: seconds % 60 })
})
let timer: ReturnType<typeof setInterval> | undefined
watch(active, value => {
  clearInterval(timer); now.value = Date.now()
  if (value) timer = setInterval(() => { now.value = Date.now() }, 1000)
}, { immediate: true })
watch(() => props.src, () => { dimensions.value = ''; loadedDuration.value = null; lightboxOpen.value = false })
onBeforeUnmount(() => clearInterval(timer))
function imageLoaded(event: Event) {
  const image = event.currentTarget as HTMLImageElement
  dimensions.value = image.naturalWidth && image.naturalHeight ? `${image.naturalWidth} × ${image.naturalHeight}` : ''
}
function videoLoaded(event: Event) {
  const video = event.currentTarget as HTMLVideoElement
  dimensions.value = video.videoWidth && video.videoHeight ? `${video.videoWidth} × ${video.videoHeight}` : ''
  loadedDuration.value = Number.isFinite(video.duration) ? video.duration : null
}
</script>

<template>
  <article class="clip-media-result" :class="{ 'is-active': active, 'is-failed': status === 4 }">
    <header class="clip-media-result__header"><strong>{{ name }}</strong><span class="clip-media-result__status" role="status"><LoaderCircle v-if="active" :size="13" aria-hidden="true" />{{ title }}</span><slot name="action" /></header>
    <div class="clip-media-result__stage" :class="{ 'is-active': active, 'has-media': src }" :style="{ aspectRatio: aspectRatio.replace(':', '/') }" :aria-busy="active">
      <button v-if="src && kind === 'image'" type="button" class="clip-media-result__image" :aria-label="tr('放大查看当前图片')" @click="lightboxOpen = true"><img :src="mediaUrl(src)" :alt="name" @load="imageLoaded"><span class="clip-media-result__zoom"><Maximize2 :size="15" />{{ tr('放大查看') }}</span></button>
      <video v-else-if="src && kind === 'video'" :src="mediaUrl(src)" controls playsinline preload="metadata" @loadedmetadata="videoLoaded" />
      <div v-if="active" class="clip-media-result__progress">
        <div class="clip-media-result__spinner" aria-hidden="true"><LoaderCircle :size="32" /></div>
        <strong>{{ title }}</strong><span class="clip-media-result__elapsed"><Clock3 :size="14" aria-hidden="true" />{{ tr('已用时') }} {{ elapsed }}</span>
        <p>{{ tr('生成完成后会自动显示，无需重复提交') }}</p>
      </div>
      <div v-else-if="!src" class="clip-media-result__empty"><AlertCircle v-if="status === 4" :size="30" /><Image v-else-if="kind === 'image'" :size="30" /><Film v-else :size="30" /><strong>{{ title }}</strong></div>
    </div>
    <p v-if="error" class="clip-media-result__error" role="alert">{{ error }}</p>
    <p v-if="status === 3 && requestedFormat === 'gif' && actualFormat === 'PNG'" class="clip-media-result__format-note" role="status">{{ tr('当前文件为 PNG 静态图') }}</p>
    <dl class="clip-media-result__info">
      <div><dt>{{ tr('生成耗时') }}</dt><dd><time v-if="elapsedSeconds !== null" :datetime="`PT${elapsedSeconds}S`">{{ elapsed }}</time><span v-else>{{ elapsed }}</span></dd></div>
      <div><dt>{{ tr(kind === 'image' ? '图片尺寸' : '视频尺寸') }}</dt><dd>{{ dimensions || tr(src ? '读取中' : '待生成') }}</dd></div>
      <div v-if="kind === 'image'"><dt>{{ tr('文件格式') }}</dt><dd>{{ actualFormat || (requestedFormat ? tr('等待返回') : '—') }}</dd></div>
      <div><dt>{{ tr('清晰度') }} / {{ tr('比例') }}</dt><dd>{{ resolution || '—' }} · {{ aspectRatio }}</dd></div>
      <div v-if="kind === 'video'"><dt>{{ tr('视频时长') }}</dt><dd>{{ loadedDuration !== null ? tr('{p0} 秒', { p0: Math.round(loadedDuration * 10) / 10 }) : duration ? tr('{p0} 秒', { p0: duration }) : '—' }}</dd></div>
      <div v-if="showCosts !== false"><dt>{{ tr('预计费用') }}</dt><dd>{{ estimatedCost != null ? money(Number(estimatedCost), estimateCurrency) : tr('暂未报价') }}</dd></div>
      <div v-if="showCosts !== false"><dt>{{ tr('实际费用') }}</dt><dd class="clip-media-result__cost">{{ actualCost }}</dd></div>
      <div class="clip-media-result__model"><dt>{{ tr('生成模型') }}</dt><dd>{{ model || '—' }}</dd></div>
    </dl>
    <details class="clip-media-result__prompt" open><summary>{{ tr('提示词') }}</summary><p>{{ prompt || tr('暂无提示词') }}</p></details>
    <ImageLightbox v-if="kind === 'image' && src" :open="lightboxOpen" :src="mediaUrl(src)" :alt="name" @close="lightboxOpen = false" />
  </article>
</template>

<style scoped>
.clip-media-result { min-width: 0; overflow: hidden; border: 1px solid var(--app-border); border-radius: 14px; background: var(--app-surface); color: var(--app-text); }
.clip-media-result__header { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; padding: 14px 18px; }.clip-media-result__header > strong { font-size: 13px; font-weight: 600; }.clip-media-result__header > :last-child:not(.clip-media-result__status) { margin-left: auto; }
.clip-media-result__status { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; color: var(--app-text-secondary); }.is-active .clip-media-result__status { color: var(--app-accent); }
.clip-media-result__stage { position: relative; display: flex; align-items: center; justify-content: center; width: 100%; min-height: 240px; max-height: 480px; overflow: hidden; background: var(--app-surface-muted); }
.clip-media-result__stage.is-active { background: radial-gradient(ellipse at 20% 25%, color-mix(in srgb, var(--app-accent) 24%, transparent), transparent 60%), radial-gradient(ellipse at 85% 80%, color-mix(in srgb, var(--app-accent) 12%, transparent), transparent 55%), var(--app-surface-muted); }
.clip-media-result__image { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; padding: 0; border: 0; background: transparent; cursor: zoom-in; }.clip-media-result__image img, .clip-media-result__stage video { display: block; width: 100%; height: 100%; object-fit: contain; }.clip-media-result__stage video { position: absolute; inset: 0; }
.clip-media-result__zoom { position: absolute; right: 14px; bottom: 14px; display: flex; align-items: center; gap: 6px; border: 1px solid var(--app-border); border-radius: 8px; padding: 7px 10px; background: var(--app-surface); color: var(--app-text); font-size: 11px; opacity: 0; transition: opacity .15s; }.clip-media-result__image:hover .clip-media-result__zoom, .clip-media-result__image:focus-visible .clip-media-result__zoom { opacity: 1; }.clip-media-result__image:focus-visible { outline: 2px solid var(--app-accent); outline-offset: -3px; }
.clip-media-result__progress, .clip-media-result__empty { grid-area: 1 / 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 14px; text-align: center; padding: 28px 16px; }.has-media .clip-media-result__progress { position: absolute; inset: 0; backdrop-filter: blur(8px); background: color-mix(in srgb, var(--app-surface) 86%, transparent); }
.clip-media-result__spinner { display: grid; place-items: center; width: 78px; height: 78px; border: 1px solid color-mix(in srgb, var(--app-accent) 25%, var(--app-border)); border-radius: 24px; background: color-mix(in srgb, var(--app-accent) 12%, var(--app-surface)); color: var(--app-accent); box-shadow: 0 12px 50px color-mix(in srgb, var(--app-accent) 14%, transparent); }.clip-media-result__progress strong { font-size: 18px; font-weight: 600; }.clip-media-result__elapsed { display: flex; align-items: center; gap: 6px; font-size: 14px; font-variant-numeric: tabular-nums; color: var(--app-text-secondary); }.clip-media-result__progress p { margin: 0; color: var(--app-text-secondary); font-size: 12px; line-height: 1.7; }.clip-media-result__empty { color: var(--app-text-muted); font-size: 13px; }
.clip-media-result__info { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 20px; margin: 0; padding: 20px; border-top: 1px solid var(--app-border); }.clip-media-result__info > div { min-width: 0; }.clip-media-result__info dt { font-size: 11px; color: var(--app-text-muted); margin-bottom: 7px; }.clip-media-result__info dd { margin: 0; font-size: 13px; font-weight: 500; line-height: 1.6; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }.clip-media-result__info .clip-media-result__cost { color: var(--app-accent); }
.clip-media-result__prompt { border-top: 1px solid var(--app-border); padding: 15px 20px; font-size: 12px; }.clip-media-result__prompt summary { color: var(--app-text-secondary); cursor: pointer; }.clip-media-result__prompt summary:focus-visible { outline: 2px solid var(--app-accent); outline-offset: 3px; }.clip-media-result__prompt p { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 180px; overflow-y: auto; margin: 12px 0 0; line-height: 1.8; color: var(--app-text-secondary); }
.clip-media-result__error { margin: 0; padding: 14px 20px; font-size: 12px; line-height: 1.7; overflow-wrap: anywhere; color: var(--app-danger); background: color-mix(in srgb, var(--app-danger) 8%, var(--app-surface)); }
.clip-media-result__format-note { margin: 0; padding: 12px 20px; color: var(--app-text-secondary); background: var(--app-accent-soft); font-size: 12px; }
.is-active .lucide-loader-circle { animation: clip-generation-spin 1.4s linear infinite; }@keyframes clip-generation-spin { to { transform: rotate(360deg); } }@media(prefers-reduced-motion: reduce) { .is-active .lucide-loader-circle { animation: none; }.clip-media-result__zoom { transition: none; } }
@media(max-width: 650px) { .clip-media-result__info { grid-template-columns: repeat(2, minmax(0, 1fr)); padding: 16px; gap: 16px; }.clip-media-result__header { padding: 12px 16px; }.clip-media-result__stage { min-height: 240px; }.clip-media-result__zoom { opacity: 1; } }
</style>
