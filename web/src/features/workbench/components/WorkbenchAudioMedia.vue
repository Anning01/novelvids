<script setup lang="ts">
import { Music2, Pause, Play, Volume2, VolumeX } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'

const props = withDefaults(defineProps<{
  src: string
  title: string
  previewUrl?: string
  sourceLabel?: string
  durationSeconds?: number
}>(), {
  previewUrl: '',
  sourceLabel: '参考音频',
  durationSeconds: 0,
})

const player = ref<HTMLAudioElement | null>(null)
const playing = ref(false)
const muted = ref(false)
const currentTime = ref(0)
const measuredDuration = ref(0)

const duration = computed(() => measuredDuration.value || props.durationSeconds || 0)
const progress = computed(() => duration.value > 0
  ? Math.min(100, Math.max(0, currentTime.value / duration.value * 100))
  : 0)
const progressStyle = computed(() => ({ '--audio-progress': `${progress.value}%` }))

watch(() => props.src, () => {
  const audio = player.value
  if (audio && !audio.paused) audio.pause()
  playing.value = false
  currentTime.value = 0
  measuredDuration.value = 0
})

function formatTime(seconds: number) {
  if (!Number.isFinite(seconds) || seconds <= 0) return '0:00'
  const rounded = Math.floor(seconds)
  return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, '0')}`
}

function captureDuration() {
  const audio = player.value
  measuredDuration.value = audio && Number.isFinite(audio.duration) ? audio.duration : 0
}

function captureTime() {
  currentTime.value = player.value?.currentTime ?? 0
}

function togglePlayback() {
  const audio = player.value
  if (!audio) return
  if (playing.value) {
    audio.pause()
    playing.value = false
    return
  }
  void audio.play().then(() => {
    playing.value = true
  }).catch(() => {
    playing.value = false
  })
}

function seek(event: Event) {
  const audio = player.value
  if (!audio || duration.value <= 0) return
  const nextTime = Number((event.currentTarget as HTMLInputElement).value)
  audio.currentTime = nextTime
  currentTime.value = nextTime
}

function toggleMuted() {
  const audio = player.value
  if (!audio) return
  audio.muted = !audio.muted
  muted.value = audio.muted
}

function handleEnded() {
  playing.value = false
  currentTime.value = 0
}
</script>

<template>
  <div class="workbench-audio-media nodrag nowheel">
    <audio
      ref="player"
      :src="src"
      preload="metadata"
      @loadedmetadata="captureDuration"
      @durationchange="captureDuration"
      @timeupdate="captureTime"
      @ended="handleEnded"
    />
    <div class="workbench-audio-media__identity">
      <img v-if="previewUrl" :src="previewUrl" alt="" aria-hidden="true" loading="lazy" decoding="async">
      <span v-else><Music2 :size="17" aria-hidden="true" /></span>
    </div>
    <button type="button" class="workbench-audio-media__play" :aria-label="playing ? `暂停 ${title}` : `播放 ${title}`" @click="togglePlayback">
      <Pause v-if="playing" :size="15" fill="currentColor" aria-hidden="true" />
      <Play v-else :size="15" fill="currentColor" aria-hidden="true" />
    </button>
    <div class="workbench-audio-media__body">
      <div class="workbench-audio-media__heading">
        <span><strong :title="title">{{ title }}</strong><small>{{ sourceLabel }}</small></span>
        <time>{{ formatTime(currentTime) }} / {{ formatTime(duration) }}</time>
      </div>
      <input
        class="workbench-audio-media__range"
        type="range"
        min="0"
        :max="duration || 0"
        step="0.01"
        :value="currentTime"
        :style="progressStyle"
        :aria-label="`${title} 播放进度`"
        @input="seek"
      >
    </div>
    <button type="button" class="workbench-audio-media__volume" :aria-label="muted ? '恢复声音' : '静音'" @click="toggleMuted">
      <VolumeX v-if="muted" :size="16" aria-hidden="true" />
      <Volume2 v-else :size="16" aria-hidden="true" />
    </button>
  </div>
</template>

<style scoped>
.workbench-audio-media {
  display: grid;
  grid-template-columns: 38px 32px minmax(0, 1fr) 28px;
  align-items: center;
  gap: 8px;
  min-height: 68px;
  padding: 10px;
  border: 1px solid #403a35;
  border-radius: 12px;
  color: #eee9e2;
  background:
    radial-gradient(circle at 10% 0%, rgb(143 115 223 / 13%), transparent 40%),
    linear-gradient(145deg, #211e1b, #191715);
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 3%);
}
.workbench-audio-media audio { display: none; }
.workbench-audio-media__identity {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  overflow: hidden;
  border: 1px solid #4a433d;
  border-radius: 10px;
  color: #b8a6ef;
  background: #2b2632;
}
.workbench-audio-media__identity img { width: 100%; height: 100%; object-fit: cover; }
.workbench-audio-media button {
  display: grid;
  margin: 0;
  padding: 0;
  place-items: center;
  border: 0;
  color: inherit;
  cursor: pointer;
  transition: 140ms ease;
}
.workbench-audio-media button:focus-visible,
.workbench-audio-media__range:focus-visible { outline: 2px solid #a88cf4; outline-offset: 2px; }
.workbench-audio-media__play {
  width: 32px;
  height: 32px;
  border-radius: 999px;
  color: #171315 !important;
  background: #b29af2;
  box-shadow: 0 4px 14px rgb(122 91 202 / 25%);
}
.workbench-audio-media__play:hover { color: #110f10 !important; background: #c2adfa; transform: translateY(-1px); }
.workbench-audio-media__play :deep(svg) { margin-left: 1px; }
.workbench-audio-media__body { display: grid; min-width: 0; gap: 8px; }
.workbench-audio-media__heading { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 8px; }
.workbench-audio-media__heading > span { display: flex; min-width: 0; align-items: baseline; gap: 6px; }
.workbench-audio-media__heading strong { overflow: hidden; font-size: 11px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.workbench-audio-media__heading small { flex: none; color: #887f77; font-size: 9px; }
.workbench-audio-media__heading time { flex: none; color: #aaa198; font-size: 9px; font-variant-numeric: tabular-nums; }
.workbench-audio-media__range {
  width: 100%;
  height: 3px;
  margin: 0;
  border-radius: 999px;
  outline: none;
  appearance: none;
  cursor: pointer;
  background: linear-gradient(to right, #a88cf4 var(--audio-progress), #4b4540 var(--audio-progress));
}
.workbench-audio-media__range::-webkit-slider-thumb {
  width: 10px;
  height: 10px;
  border: 2px solid #211e1b;
  border-radius: 999px;
  appearance: none;
  background: #c2adfa;
  box-shadow: 0 0 0 1px #a88cf4;
}
.workbench-audio-media__range::-moz-range-thumb {
  width: 8px;
  height: 8px;
  border: 2px solid #211e1b;
  border-radius: 999px;
  background: #c2adfa;
}
.workbench-audio-media__volume { width: 28px; height: 28px; border-radius: 7px; color: #aaa198 !important; background: transparent; }
.workbench-audio-media__volume:hover { color: #eee9e2 !important; background: #302b27; }
@media (prefers-reduced-motion: reduce) {
  .workbench-audio-media button { transition: none; }
}
</style>
