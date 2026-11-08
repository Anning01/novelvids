<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Clock3, LoaderCircle, RefreshCw } from 'lucide-vue-next'
import { tr } from '@/i18n'
import { TaskStatusEnum, type Video } from '@/types'

const props = defineProps<{ video?: Video; syncDelayed?: boolean }>()
const now = ref(Date.now())
const submittedLocallyAt = Date.now()
const active = computed(() => !props.video || [TaskStatusEnum.PENDING, TaskStatusEnum.PROCESSING, TaskStatusEnum.QUEUED].includes(props.video.status))
let timer: ReturnType<typeof setInterval> | undefined
watch(active, running => {
  clearInterval(timer)
  now.value = Date.now()
  if (running) timer = setInterval(() => { now.value = Date.now() }, 1000)
}, { immediate: true })
onBeforeUnmount(() => clearInterval(timer))
const elapsedSeconds = computed(() => {
  const start = props.video ? Date.parse(props.video.created_at) : submittedLocallyAt
  return Number.isFinite(start) ? Math.max(0, Math.floor((now.value - start) / 1000)) : null
})
const elapsed = computed(() => {
  const seconds = elapsedSeconds.value
  if (seconds === null) return tr('正在同步计时信息')
  return seconds < 60 ? tr('{p0} 秒', { p0: seconds })
    : tr('{p0} 分 {p1} 秒', { p0: Math.floor(seconds / 60), p1: seconds % 60 })
})
const queued = computed(() => props.video && [TaskStatusEnum.PENDING, TaskStatusEnum.QUEUED].includes(props.video.status))
const title = computed(() => props.syncDelayed ? tr('视频状态暂未同步')
  : !props.video ? tr('正在提交生成请求') : queued.value ? tr('排队等待生成') : tr('视频生成中'))
</script>

<template>
  <div class="video-generation-progress">
    <div class="video-generation-progress__icon" aria-hidden="true"><RefreshCw v-if="syncDelayed" :size="26" /><LoaderCircle v-else :size="28" /></div>
    <strong class="video-generation-progress__title" role="status">{{ title }}</strong>
    <div class="video-generation-progress__timer">
      <span><Clock3 :size="14" aria-hidden="true" />{{ tr('已用时') }}</span>
      <time v-if="elapsedSeconds !== null" :datetime="`PT${elapsedSeconds}S`">{{ elapsed }}</time>
      <span v-else class="video-generation-progress__unknown">{{ elapsed }}</span>
    </div>
    <p>{{ syncDelayed ? tr('可刷新视频状态，不必重新生成') : video ? tr('从提交起计时，完成后将在这里自动播放') : tr('正在保存任务，请稍候') }}</p>
  </div>
</template>

<style scoped>
.video-generation-progress { width: 100%; height: 100%; min-height: 240px; padding: 32px 24px; box-sizing: border-box; display: flex; flex-direction: column; justify-content: center; align-items: center; gap: 16px; text-align: center; color: var(--app-text); background: var(--app-surface-muted); }
.video-generation-progress__icon { display: grid; place-items: center; width: 58px; height: 58px; border-radius: 18px; color: var(--app-accent); background: var(--app-accent-soft); }
.video-generation-progress__icon .lucide-loader-circle { animation: progress-spin 1.2s linear infinite; }
.video-generation-progress__title { font-size: 16px; font-weight: 600; line-height: 1.5; }
.video-generation-progress__timer { display: grid; justify-items: center; gap: 8px; padding: 18px 28px; min-width: 190px; border: 1px solid var(--app-border); border-radius: 14px; background: var(--app-surface); }
.video-generation-progress__timer > span:first-child { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--app-text-secondary); }
.video-generation-progress__timer time { font-size: clamp(22px, 2.5vw, 30px); font-weight: 600; font-variant-numeric: tabular-nums; line-height: 1.4; }
.video-generation-progress__unknown { font-size: 13px; color: var(--app-text-secondary); }
.video-generation-progress p { max-width: 280px; margin: 0; color: var(--app-text-secondary); font-size: 12px; line-height: 1.7; }
@keyframes progress-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .video-generation-progress__icon .lucide-loader-circle { animation: none; } }
</style>
