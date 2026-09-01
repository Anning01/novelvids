<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { Film, Play } from 'lucide-vue-next'

defineOptions({ inheritAttrs: false })

const props = withDefaults(defineProps<{
  src?: string
  poster?: string
  title: string
  controls?: boolean
  muted?: boolean
  loop?: boolean
  autoplayOnActivate?: boolean
  aspectRatio?: string
}>(), {
  src: '',
  poster: '',
  controls: true,
  muted: false,
  loop: false,
  autoplayOnActivate: true,
  aspectRatio: '',
})
const emit = defineEmits<{ activate: [] }>()
const activated = ref(false)
const video = ref<HTMLVideoElement | null>(null)

async function activate() {
  if (!props.src || activated.value) return
  activated.value = true
  emit('activate')
  await nextTick()
  if (props.autoplayOnActivate) {
    await video.value?.play().catch(() => undefined)
  }
}

watch(() => props.src, () => {
  activated.value = false
})

defineExpose({ activate, element: video })
</script>

<template>
  <div class="deferred-video-player" :style="aspectRatio ? { aspectRatio } : undefined">
    <button
      v-if="src && !activated"
      type="button"
      class="deferred-video-player__poster"
      :aria-label="`播放${title}`"
      @click="activate"
    >
      <img v-if="poster" :src="poster" :alt="`${title}封面`" loading="lazy" decoding="async">
      <span v-else class="deferred-video-player__empty"><Film :size="30" /><small>点击加载视频</small></span>
      <i aria-hidden="true"><Play :size="22" fill="currentColor" /></i>
    </button>
    <video
      v-else-if="src"
      ref="video"
      :src="src"
      :poster="poster || undefined"
      :controls="controls"
      :muted="muted"
      :loop="loop"
      playsinline
      preload="metadata"
      :aria-label="title"
      v-bind="$attrs"
    />
  </div>
</template>

<style scoped>
.deferred-video-player,.deferred-video-player > video,.deferred-video-player__poster { width: 100%; height: 100%; }
.deferred-video-player > video { display: block; object-fit: contain; }
.deferred-video-player__poster { position: relative; display: grid; place-items: center; overflow: hidden; padding: 0; border: 0; color: #fff; background: #171a22; cursor: pointer; }
.deferred-video-player__poster > img { width: 100%; height: 100%; object-fit: cover; }
.deferred-video-player__poster > i { position: absolute; display: grid; width: 54px; height: 54px; place-items: center; border: 1px solid rgb(255 255 255 / 44%); border-radius: 50%; background: rgb(20 22 29 / 68%); box-shadow: 0 8px 28px rgb(0 0 0 / 24%); font-style: normal; backdrop-filter: blur(8px); transition: transform .18s ease,background-color .18s ease; }
.deferred-video-player__poster:hover > i,.deferred-video-player__poster:focus-visible > i { background: rgb(86 81 238 / 88%); transform: scale(1.06); }
.deferred-video-player__poster:focus-visible { outline: 3px solid color-mix(in srgb,var(--app-accent) 55%,transparent); outline-offset: -3px; }
.deferred-video-player__empty { display: grid; place-items: center; gap: 8px; color: #aeb4c2; }
.deferred-video-player__empty small { font-size: 10px; }
@media (prefers-reduced-motion: reduce) { .deferred-video-player__poster > i { transition: none; } }
</style>
