<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Film, LoaderCircle } from 'lucide-vue-next'
import { tr } from '@/i18n'

const props = withDefaults(defineProps<{ src: string; poster?: string; alt?: string; fit?: 'cover' | 'contain' }>(), {
  poster: '', alt: '', fit: 'cover',
})
const root = ref<HTMLElement | null>(null)
const visible = ref(false)
const posterFailed = ref(false)
const frameReady = ref(false)
const frameFailed = ref(false)
let observer: IntersectionObserver | undefined

watch(() => [props.src, props.poster], () => {
  posterFailed.value = false
  frameReady.value = false
  frameFailed.value = false
})

function seekFirstFrame(event: Event) {
  const video = event.currentTarget as HTMLVideoElement
  // Seeking decodes a still frame without starting playback or requiring canvas/CORS access.
  if (Number.isFinite(video.duration) && video.duration > 0) video.currentTime = Math.min(.1, video.duration / 2)
}

onMounted(() => {
  if (typeof IntersectionObserver === 'undefined') { visible.value = true; return }
  observer = new IntersectionObserver(entries => {
    if (!entries.some(entry => entry.isIntersecting)) return
    visible.value = true
    observer?.disconnect()
  }, { rootMargin: '160px' })
  if (root.value) observer.observe(root.value)
})
onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <span ref="root" class="video-thumbnail" :style="{ '--thumbnail-fit': fit }" :role="alt ? 'img' : undefined" :aria-label="alt || undefined" :aria-hidden="alt ? undefined : true">
    <img v-if="poster && !posterFailed" :src="poster" alt="" loading="lazy" decoding="async" @error="posterFailed = true" />
    <template v-else>
      <video v-if="src && visible && !frameFailed" :key="src" :src="src" muted playsinline preload="metadata" tabindex="-1" aria-hidden="true"
        :class="{ 'is-ready': frameReady }" @loadedmetadata="seekFirstFrame" @loadeddata="frameReady = true" @seeked="frameReady = true" @error="frameFailed = true" />
      <span v-if="frameFailed || !src" class="video-thumbnail-state"><Film :size="23" /><small>{{ tr('封面加载失败') }}</small></span>
      <span v-else-if="!frameReady" class="video-thumbnail-state"><LoaderCircle class="video-thumbnail-spinner" :size="20" /></span>
    </template>
  </span>
</template>

<style scoped>
.video-thumbnail { position: relative; display: block; width: 100%; height: 100%; overflow: hidden; color: var(--app-text-muted); background: var(--app-surface-muted); }
.video-thumbnail > img,.video-thumbnail > video { display: block; width: 100%; height: 100%; object-fit: var(--thumbnail-fit); pointer-events: none; }
.video-thumbnail > video { opacity: 0; }.video-thumbnail > video.is-ready { opacity: 1; }
.video-thumbnail-state { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 7px; }.video-thumbnail-state small { font-size: 10px; }
.video-thumbnail-spinner { color: var(--app-accent); animation: thumbnail-spin 1s linear infinite; }
@keyframes thumbnail-spin { to { transform: rotate(360deg); } }
@media(prefers-reduced-motion:reduce) { .video-thumbnail-spinner { animation: none; } }
</style>
