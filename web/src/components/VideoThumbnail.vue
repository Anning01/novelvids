<script setup lang="ts">
import { computed, onMounted, ref, watch, type VNode } from 'vue'
import { Film, LoaderCircle } from 'lucide-vue-next'
import { tr } from '@/i18n'

const props = withDefaults(defineProps<{ src: string; poster?: string; alt?: string; fit?: 'cover' | 'contain' }>(), {
  poster: '', alt: '', fit: 'cover',
})
const MAX_FRAME_EDGE = 480
const root = ref<HTMLElement | null>(null)
const visible = ref(false)
const still = ref<HTMLCanvasElement | null>(null)
const sampler = ref<HTMLVideoElement | null>(null)
const captured = ref(false)
const posterFailed = ref(false)
const frameReady = ref(false)
const frameFailed = ref(false)
const needsFrame = computed(() => Boolean(props.src && (!props.poster || posterFailed.value) && !captured.value && !frameFailed.value))

watch(() => [props.src, props.poster], () => {
  captured.value = false
  posterFailed.value = false
  frameReady.value = false
  frameFailed.value = false
})

function seekFirstFrame(event: Event) {
  const video = event.currentTarget as HTMLVideoElement
  // Sample the opening shot without starting playback.
  if (Number.isFinite(video.duration) && video.duration > 0) video.currentTime = Math.min(.1, video.duration / 2)
}

function captureFrame(event: Event) {
  const video = event.currentTarget as HTMLVideoElement
  if (video !== sampler.value || video.seeking || captured.value) return
  frameReady.value = true
  const canvas = still.value
  if (!canvas || !video.videoWidth || !video.videoHeight) return
  const context = canvas.getContext('2d')
  if (!context) return
  const scale = Math.min(1, MAX_FRAME_EDGE / Math.max(video.videoWidth, video.videoHeight))
  canvas.width = Math.max(1, Math.round(video.videoWidth * scale))
  canvas.height = Math.max(1, Math.round(video.videoHeight * scale))
  // Display the pixels directly so remote videos need no CORS permission for readback.
  try {
    context.drawImage(video, 0, 0, canvas.width, canvas.height)
    captured.value = true
  } catch (error) {
    // Some protected or not-yet-decoded frames can only be shown by the sampler itself.
    if (!(error instanceof DOMException && ['InvalidStateError', 'SecurityError'].includes(error.name))) throw error
  }
}

function failSampler(event: Event) {
  if (event.currentTarget === sampler.value) frameFailed.value = true
}

function releaseSampler(vnode: VNode) {
  const video = vnode.el as HTMLVideoElement
  video.removeAttribute('src')
  video.load()
}

onMounted(() => {
  watch(needsFrame, (needed, _, onCleanup) => {
    visible.value = false
    if (!needed || !root.value) return
    if (typeof IntersectionObserver === 'undefined') { visible.value = true; return }
    const observer = new IntersectionObserver(entries => {
      visible.value = entries[entries.length - 1]?.isIntersecting ?? false
      if (!visible.value) frameReady.value = false
    }, { rootMargin: '160px' })
    observer.observe(root.value)
    onCleanup(() => observer.disconnect())
  }, { immediate: true })
})
</script>

<template>
  <span ref="root" class="video-thumbnail" :style="{ '--thumbnail-fit': fit }" :role="alt ? 'img' : undefined" :aria-label="alt || undefined" :aria-hidden="alt ? undefined : true">
    <img v-if="poster && !posterFailed" :src="poster" alt="" loading="lazy" decoding="async" @error="posterFailed = true" />
    <template v-else>
      <canvas v-if="src && (visible || captured) && !frameFailed" v-show="captured" ref="still" width="1" height="1" aria-hidden="true" />
      <video v-if="src && visible && !captured && !frameFailed" ref="sampler" :key="src" :src="src" muted playsinline preload="metadata" tabindex="-1" aria-hidden="true"
        :class="{ 'is-ready': frameReady }" @loadedmetadata="seekFirstFrame" @loadeddata="captureFrame" @seeked="captureFrame" @vue:unmounted="releaseSampler" @error="failSampler" />
      <span v-if="frameFailed || !src" class="video-thumbnail-state"><Film :size="23" /><small>{{ tr('封面加载失败') }}</small></span>
      <span v-else-if="!captured && !frameReady" class="video-thumbnail-state"><LoaderCircle class="video-thumbnail-spinner" :size="20" /></span>
    </template>
  </span>
</template>

<style scoped>
.video-thumbnail { position: relative; display: block; width: 100%; height: 100%; overflow: hidden; color: var(--app-text-muted); background: var(--app-surface-muted); }
.video-thumbnail > img,.video-thumbnail > video,.video-thumbnail > canvas { display: block; width: 100%; height: 100%; object-fit: var(--thumbnail-fit); pointer-events: none; }
.video-thumbnail > video { opacity: 0; }.video-thumbnail > video.is-ready { opacity: 1; }
.video-thumbnail-state { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 7px; }.video-thumbnail-state small { font-size: 10px; }
.video-thumbnail-spinner { color: var(--app-accent); animation: thumbnail-spin 1s linear infinite; }
@keyframes thumbnail-spin { to { transform: rotate(360deg); } }
@media(prefers-reduced-motion:reduce) { .video-thumbnail-spinner { animation: none; } }
</style>
