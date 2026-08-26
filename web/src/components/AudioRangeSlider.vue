<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Pause, Play } from 'lucide-vue-next'

const props = withDefaults(defineProps<{
  start: number
  end: number
  duration: number
  src?: string
  minClipDuration?: number
  maxClipDuration?: number
  step?: number
}>(), {
  src: '',
  minClipDuration: 1,
  maxClipDuration: 30,
  step: 0.1,
})

const emit = defineEmits<{
  'update:start': [value: number]
  'update:end': [value: number]
  'loaded-duration': [value: number]
}>()

const audioRef = ref<HTMLAudioElement | null>(null)
const mediaDuration = ref(0)
const currentTime = ref(props.start)
const isPlaying = ref(false)
const safeDuration = computed(() => Math.max(0, Number(props.duration) || mediaDuration.value || 0))
const startPercent = computed(() => safeDuration.value
  ? Math.min(100, Math.max(0, props.start / safeDuration.value * 100))
  : 0)
const endPercent = computed(() => safeDuration.value
  ? Math.min(100, Math.max(0, props.end / safeDuration.value * 100))
  : 0)
const selectedDuration = computed(() => Math.max(0, props.end - props.start))
const playheadPercent = computed(() => safeDuration.value
  ? Math.min(100, Math.max(0, currentTime.value / safeDuration.value * 100))
  : 0)
const selectionStyle = computed(() => ({
  left: `${startPercent.value}%`,
  width: `${Math.max(0, endPercent.value - startPercent.value)}%`,
}))
const playheadStyle = computed(() => ({ left: `${playheadPercent.value}%` }))

function roundToStep(value: number) {
  const precision = Math.max(0, (String(props.step).split('.')[1] || '').length)
  return Number((Math.round(value / props.step) * props.step).toFixed(precision))
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value))
}

function updateStart(event: Event) {
  const rawValue = Number((event.target as HTMLInputElement).value)
  const minimum = Math.max(0, props.end - props.maxClipDuration)
  const maximum = Math.max(minimum, props.end - props.minClipDuration)
  emit('update:start', roundToStep(clamp(rawValue, minimum, maximum)))
}

function updateEnd(event: Event) {
  const rawValue = Number((event.target as HTMLInputElement).value)
  const minimum = Math.min(safeDuration.value, props.start + props.minClipDuration)
  const maximum = Math.min(safeDuration.value, props.start + props.maxClipDuration)
  emit('update:end', roundToStep(clamp(rawValue, minimum, Math.max(minimum, maximum))))
}

function pausePreview() {
  const audio = audioRef.value
  if (audio && (isPlaying.value || !audio.paused)) audio.pause()
  isPlaying.value = false
}

function seekPreview(value: number) {
  const audio = audioRef.value
  const nextValue = clamp(value, 0, safeDuration.value)
  currentTime.value = nextValue
  if (audio) audio.currentTime = nextValue
}

async function togglePreview() {
  const audio = audioRef.value
  if (!audio || !safeDuration.value || props.end <= props.start) return
  if (isPlaying.value) {
    pausePreview()
    return
  }
  if (audio.currentTime < props.start || audio.currentTime >= props.end - 0.05) {
    seekPreview(props.start)
  }
  try {
    await audio.play()
    isPlaying.value = true
  } catch {
    isPlaying.value = false
  }
}

function captureDuration(event: Event) {
  const duration = (event.currentTarget as HTMLAudioElement).duration
  if (!Number.isFinite(duration) || duration <= 0) return
  mediaDuration.value = roundToStep(duration)
  emit('loaded-duration', mediaDuration.value)
  if (currentTime.value < props.start || currentTime.value > props.end) seekPreview(props.start)
}

function updatePlaybackTime(event: Event) {
  const audio = event.currentTarget as HTMLAudioElement
  currentTime.value = audio.currentTime
  if (audio.currentTime < props.end) return
  pausePreview()
  seekPreview(props.end)
}

function seekFromTimeline(event: PointerEvent) {
  if ((event.target as HTMLElement).tagName === 'INPUT') return
  const control = event.currentTarget as HTMLElement
  const bounds = control.getBoundingClientRect()
  if (!bounds.width || !safeDuration.value) return
  const nextTime = clamp(
    (event.clientX - bounds.left) / bounds.width * safeDuration.value,
    props.start,
    props.end,
  )
  seekPreview(roundToStep(nextTime))
}

function formatTime(value: number) {
  const seconds = Math.max(0, Number(value) || 0)
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds - minutes * 60
  const formatted = Math.abs(remainder - Math.round(remainder)) < 0.05
    ? String(Math.round(remainder)).padStart(2, '0')
    : remainder.toFixed(1).padStart(4, '0')
  return `${minutes}:${formatted}`
}

watch(() => props.start, value => seekPreview(value))
watch(() => props.end, value => {
  if (currentTime.value > value) seekPreview(value)
})
watch(() => props.src, () => {
  pausePreview()
  mediaDuration.value = 0
  currentTime.value = props.start
})

onBeforeUnmount(pausePreview)
</script>

<template>
  <section
    class="audio-range"
    role="group"
    :aria-label="`音频裁剪区间，已选 ${selectedDuration.toFixed(1)} 秒`"
  >
    <audio
      ref="audioRef"
      class="audio-range__media"
      :src="src"
      preload="metadata"
      @loadedmetadata="captureDuration"
      @timeupdate="updatePlaybackTime"
      @ended="pausePreview"
    />
    <div class="audio-range__preview">
      <button
        type="button"
        class="audio-range__play"
        :aria-label="isPlaying ? '暂停裁剪片段' : '从裁剪起点播放'"
        :disabled="!safeDuration || end <= start"
        @click="togglePreview"
      >
        <Pause v-if="isPlaying" :size="14" fill="currentColor" />
        <Play v-else :size="14" fill="currentColor" />
      </button>
      <span><strong>{{ formatTime(currentTime) }}</strong><small>/ {{ formatTime(end) }}</small></span>
      <span class="audio-range__preview-label">从裁剪起点试听</span>
    </div>
    <header>
      <span><small>开始</small><strong>{{ formatTime(start) }}</strong></span>
      <span class="audio-range__selected">已选 {{ selectedDuration.toFixed(1) }}s</span>
      <span><small>结束</small><strong>{{ formatTime(end) }}</strong></span>
    </header>
    <div class="audio-range__control" @pointerdown="seekFromTimeline">
      <div class="audio-range__track" aria-hidden="true">
        <span class="audio-range__selection" :style="selectionStyle" />
        <span class="audio-range__playhead" :style="playheadStyle" />
      </div>
      <input
        class="audio-range__input audio-range__input--start"
        type="range"
        min="0"
        :max="safeDuration"
        :step="step"
        :value="start"
        aria-label="裁剪开始时间"
        :aria-valuetext="formatTime(start)"
        @pointerdown.stop
        @input="updateStart"
      />
      <input
        class="audio-range__input audio-range__input--end"
        type="range"
        min="0"
        :max="safeDuration"
        :step="step"
        :value="end"
        aria-label="裁剪结束时间"
        :aria-valuetext="formatTime(end)"
        @pointerdown.stop
        @input="updateEnd"
      />
    </div>
    <footer aria-hidden="true"><span>0:00</span><span>{{ formatTime(safeDuration) }}</span></footer>
  </section>
</template>

<style scoped>
.audio-range { display: grid; gap: 7px; padding: 8px 2px 2px; user-select: none; }
.audio-range__media { display: none; }
.audio-range__preview { display: grid; min-height: 36px; grid-template-columns: 30px auto 1fr; align-items: center; gap: 8px; padding: 3px 8px 3px 3px; border: 1px solid color-mix(in srgb,var(--app-accent) 14%,var(--app-border)); border-radius: 10px; background: color-mix(in srgb,var(--app-accent) 3%,var(--app-surface-muted)); }
.audio-range__play { display: grid; width: 30px; height: 30px; place-items: center; padding: 0; border: 0; border-radius: 8px; color: #fff; background: var(--app-accent); cursor: pointer; transition: transform .15s ease,box-shadow .15s ease; }
.audio-range__play:hover:not(:disabled) { box-shadow: 0 4px 12px color-mix(in srgb,var(--app-accent) 30%,transparent); transform: translateY(-1px); }
.audio-range__play:focus-visible { outline: 2px solid var(--app-accent); outline-offset: 2px; }
.audio-range__play:disabled { opacity: .45; cursor: not-allowed; }
.audio-range__preview > span { display: flex; align-items: baseline; gap: 4px; font-variant-numeric: tabular-nums; }
.audio-range__preview strong { font-size: 11px; }.audio-range__preview small { color: var(--app-text-muted); font-size: 9px; }
.audio-range__preview-label { justify-self: end; color: var(--app-text-muted); font-size: 9px; }
.audio-range > header,.audio-range > footer { display: flex; align-items: center; justify-content: space-between; }
.audio-range > header > span:not(.audio-range__selected) { display: flex; min-width: 72px; align-items: baseline; gap: 5px; }
.audio-range > header > span:last-child { justify-content: flex-end; }
.audio-range small,.audio-range > footer { color: var(--app-text-muted); font-size: 9px; }
.audio-range strong { color: var(--app-text); font-size: 11px; font-variant-numeric: tabular-nums; }
.audio-range__selected { padding: 3px 8px; border-radius: 999px; color: var(--app-accent); background: var(--app-accent-soft); font-size: 9px; font-weight: 700; font-variant-numeric: tabular-nums; }
.audio-range__control { position: relative; height: 28px; cursor: pointer; }
.audio-range__track { position: absolute; top: 50%; right: 9px; left: 9px; height: 5px; overflow: visible; border-radius: 999px; background: color-mix(in srgb,var(--app-text-muted) 22%,transparent); transform: translateY(-50%); }
.audio-range__selection { position: absolute; top: 0; bottom: 0; border-radius: inherit; background: linear-gradient(90deg,var(--app-accent),color-mix(in srgb,var(--app-accent) 72%,#8c7bff)); }
.audio-range__playhead { position: absolute; z-index: 2; top: 50%; width: 2px; height: 17px; border-radius: 999px; background: var(--app-text); box-shadow: 0 0 0 2px var(--app-surface); transform: translate(-1px,-50%); pointer-events: none; }
.audio-range__input { position: absolute; z-index: 2; inset: 0; width: 100%; height: 28px; margin: 0; appearance: none; outline: none; background: transparent; pointer-events: none; }
.audio-range__input::-webkit-slider-runnable-track { height: 5px; background: transparent; }
.audio-range__input::-moz-range-track { height: 5px; background: transparent; }
.audio-range__input::-webkit-slider-thumb { width: 18px; height: 18px; margin-top: -6.5px; appearance: none; border: 3px solid var(--app-surface); border-radius: 50%; background: var(--app-accent); box-shadow: 0 1px 5px rgb(45 46 120 / 28%); cursor: grab; pointer-events: auto; transition: box-shadow .15s ease,transform .15s ease; }
.audio-range__input::-moz-range-thumb { width: 12px; height: 12px; border: 3px solid var(--app-surface); border-radius: 50%; background: var(--app-accent); box-shadow: 0 1px 5px rgb(45 46 120 / 28%); cursor: grab; pointer-events: auto; transition: box-shadow .15s ease,transform .15s ease; }
.audio-range__input:focus-visible::-webkit-slider-thumb { box-shadow: 0 0 0 4px color-mix(in srgb,var(--app-accent) 22%,transparent),0 1px 5px rgb(45 46 120 / 28%); transform: scale(1.08); }
.audio-range__input:focus-visible::-moz-range-thumb { box-shadow: 0 0 0 4px color-mix(in srgb,var(--app-accent) 22%,transparent),0 1px 5px rgb(45 46 120 / 28%); transform: scale(1.08); }
.audio-range__input:active::-webkit-slider-thumb { cursor: grabbing; transform: scale(1.12); }
.audio-range__input:active::-moz-range-thumb { cursor: grabbing; transform: scale(1.12); }
.audio-range__input--start { z-index: 3; }
@media (pointer: coarse) { .audio-range__control,.audio-range__input { height: 36px; }.audio-range__input::-webkit-slider-thumb { width: 22px; height: 22px; margin-top: -8.5px; }.audio-range__input::-moz-range-thumb { width: 16px; height: 16px; } }
@media (max-width: 480px) { .audio-range__preview-label { display: none; } }
</style>
