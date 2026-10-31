<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { LoaderCircle } from 'lucide-vue-next'
import { tr } from '@/i18n'

const props = withDefaults(defineProps<{
  src: string
  nextSrc?: string
  poster?: string
  title: string
  muted?: boolean
  playbackRate?: number
}>(), { nextSrc: '', poster: '', muted: false, playbackRate: 1 })
const emit = defineEmits<{
  play: []
  pause: []
  ended: []
  timeupdate: [seconds: number]
  error: []
  click: []
}>()
const sources = ref(['', ''])
const activeSlot = ref(0)
const visibleSlot = ref(0)
const buffering = ref(false)
const elements: Array<HTMLVideoElement | null> = [null, null]
let command: AbortController | null = null
let wantsPlayback = false
let disposed = false

function setElement(index: number, element: unknown) {
  elements[index] = element instanceof HTMLVideoElement ? element : null
}

function preloadNext() {
  // Keep the previous decoded frame until the replacement can be displayed.
  if (props.src && visibleSlot.value !== activeSlot.value) return
  const spare = 1 - activeSlot.value
  const next = props.nextSrc === props.src ? '' : props.nextSrc
  if (sources.value[spare] !== next) sources.value[spare] = next
}

function present(index: number) {
  const element = elements[index]
  if (disposed || index !== activeSlot.value || !props.src || element?.seeking
    || sources.value[index] !== props.src || (element?.readyState ?? 0) < HTMLMediaElement.HAVE_CURRENT_DATA) return
  visibleSlot.value = index
  buffering.value = false
  preloadNext()
}

function configure() {
  elements.forEach((element, index) => {
    if (!element) return
    element.muted = index !== activeSlot.value || props.muted
    element.playbackRate = props.playbackRate
  })
}

function pause() {
  command?.abort()
  command = null
  wantsPlayback = false
  buffering.value = false
  elements.forEach(element => element?.pause())
}

watch(() => props.src, src => {
  command?.abort()
  command = null
  wantsPlayback = false
  buffering.value = false
  if (src) {
    const preloaded = sources.value.indexOf(src)
    const slot = preloaded >= 0 ? preloaded : sources.value[activeSlot.value] ? 1 - activeSlot.value : activeSlot.value
    activeSlot.value = slot
    sources.value[slot] = src
  }
  elements.forEach(element => element?.pause())
  configure()
  preloadNext()
  void nextTick(() => present(activeSlot.value))
}, { immediate: true, flush: 'sync' })
watch(() => props.nextSrc, preloadNext)
watch(() => [props.muted, props.playbackRate], configure)

function waitForMetadata(video: HTMLVideoElement, signal: AbortSignal) {
  if (signal.aborted) return Promise.reject(new DOMException('Playback changed', 'AbortError'))
  if (video.error) return Promise.reject(new Error('Video could not be loaded'))
  if (video.readyState >= HTMLMediaElement.HAVE_METADATA) return Promise.resolve()
  return new Promise<void>((resolve, reject) => {
    const cleanup = () => {
      video.removeEventListener('loadedmetadata', ready)
      video.removeEventListener('error', failed)
      signal.removeEventListener('abort', cancelled)
    }
    const ready = () => { cleanup(); resolve() }
    const failed = () => { cleanup(); reject(new Error('Video could not be loaded')) }
    const cancelled = () => { cleanup(); reject(new DOMException('Playback changed', 'AbortError')) }
    video.addEventListener('loadedmetadata', ready, { once: true })
    video.addEventListener('error', failed, { once: true })
    signal.addEventListener('abort', cancelled, { once: true })
  })
}

async function start(startTime = 0, autoplay = true) {
  command?.abort()
  const request = new AbortController()
  command = request
  wantsPlayback = autoplay
  buffering.value = autoplay
  await nextTick()
  const index = activeSlot.value
  const video = elements[index]
  if (!video || !props.src || request.signal.aborted) return
  try {
    if (video.error) video.load()
    await waitForMetadata(video, request.signal)
    if (request.signal.aborted) return
    configure()
    const target = Math.min(Math.max(0, startTime), Number.isFinite(video.duration) ? video.duration : startTime)
    if (Math.abs(video.currentTime - target) > .001) video.currentTime = target
    if (autoplay) {
      await video.play()
      if (request.signal.aborted) return
    }
    present(index)
  } catch (error) {
    if (command === request) { buffering.value = false; wantsPlayback = false }
    throw error
  }
}

function onPlay(index: number) {
  if (index === activeSlot.value && props.src) emit('play')
}
function onPause(index: number) {
  if (index === activeSlot.value && props.src && !elements[index]?.ended) emit('pause')
}
function onError(index: number) {
  if (index !== activeSlot.value || !props.src) return
  wantsPlayback = false
  buffering.value = false
  emit('error')
}
function onWaiting(index: number) {
  if (index === activeSlot.value && wantsPlayback) buffering.value = true
}

onBeforeUnmount(() => {
  disposed = true
  pause()
  elements.forEach(element => {
    if (!element) return
    element.removeAttribute('src')
    element.load()
  })
})
defineExpose({ start, pause })
</script>

<template>
  <div class="buffered-video-player" :aria-busy="buffering || undefined">
    <video v-for="index in [0, 1]" :key="index" :ref="element => setElement(index, element)"
      :src="sources[index] || undefined" :poster="index === activeSlot ? poster || undefined : undefined"
      :class="{ 'is-visible': Boolean(src) && index === visibleSlot }"
      :muted="index !== activeSlot || muted" preload="auto" playsinline
      :aria-label="index === activeSlot ? title : undefined" :aria-hidden="index !== activeSlot || !src"
      tabindex="-1" @loadedmetadata="configure" @loadeddata="present(index)" @seeked="present(index)"
      @playing="present(index)" @waiting="onWaiting(index)" @stalled="onWaiting(index)" @error="onError(index)"
      @play="onPlay(index)" @pause="onPause(index)" @ended="index === activeSlot && src && emit('ended')"
      @timeupdate="index === activeSlot && src && emit('timeupdate', elements[index]?.currentTime || 0)"
      @click="emit('click')" />
    <span v-if="buffering" class="buffered-video-player__status" role="status"><LoaderCircle :size="15" />{{ tr('正在缓冲视频') }}</span>
  </div>
</template>

<style scoped>
.buffered-video-player { position: relative; width: 100%; height: 100%; min-width: 0; min-height: 0; overflow: hidden; }
video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; opacity: 0; pointer-events: none; }
video.is-visible { opacity: 1; pointer-events: auto; cursor: pointer; }
.buffered-video-player__status { position: absolute; bottom: 14px; left: 14px; display: inline-flex; align-items: center; gap: 6px; padding: 7px 10px; border-radius: 8px; color: var(--app-text); background: var(--app-surface); font-size: 11px; pointer-events: none; }
.buffered-video-player__status svg { color: var(--app-accent); animation: buffer-spin .9s linear infinite; }
@keyframes buffer-spin { to { transform: rotate(360deg); } }
@media(prefers-reduced-motion: reduce) { .buffered-video-player__status svg { animation: none; } }
</style>
