<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Maximize2, Minus, Plus, RotateCcw, X } from 'lucide-vue-next'

const props = withDefaults(defineProps<{
  open: boolean
  src: string
  alt: string
  format?: string
}>(), {
  format: '',
})
const emit = defineEmits<{ close: [] }>()

const zoom = ref(1)
const dimensions = ref('')

const normalizedFormat = computed(() => {
  if (props.format) return props.format.toUpperCase().replace('JPG', 'JPEG')
  const dataMime = props.src.match(/^data:image\/([^;,]+)/i)?.[1]
  if (dataMime) return dataMime.toUpperCase().replace('JPG', 'JPEG')
  const extension = props.src.split(/[?#]/, 1)[0]?.match(/\.([a-z0-9]+)$/i)?.[1]
  return extension?.toUpperCase().replace('JPG', 'JPEG') || 'IMAGE'
})
const metadata = computed(() => [dimensions.value, normalizedFormat.value].filter(Boolean).join(' / '))
const zoomLabel = computed(() => `${Math.round(zoom.value * 100)}%`)

function onImageLoad(event: Event) {
  const image = event.currentTarget as HTMLImageElement
  dimensions.value = image.naturalWidth && image.naturalHeight
    ? `${image.naturalWidth} × ${image.naturalHeight}`
    : ''
}

function zoomIn() {
  zoom.value = Math.min(3, Number((zoom.value + 0.25).toFixed(2)))
}

function zoomOut() {
  zoom.value = Math.max(0.5, Number((zoom.value - 0.25).toFixed(2)))
}

function resetZoom() {
  zoom.value = 1
}

function toggleZoom() {
  zoom.value = zoom.value === 1 ? 2 : 1
}

watch(() => props.open, open => {
  if (!open) return
  zoom.value = 1
  dimensions.value = ''
})
</script>

<template>
  <Teleport to="body">
    <Transition name="image-lightbox">
      <div v-if="open" class="image-lightbox" role="dialog" aria-modal="true" aria-label="图片放大查看" @click.self="emit('close')">
        <header class="image-lightbox__toolbar">
          <div>
            <Maximize2 :size="16" />
            <span>{{ metadata }}</span>
          </div>
          <nav aria-label="图片缩放控制">
            <AppButton type="button" variant="ghost" size="sm" icon-only aria-label="缩小图片" title="缩小" :disabled="zoom <= 0.5" @click="zoomOut"><Minus :size="16" /></AppButton>
            <output aria-live="polite">{{ zoomLabel }}</output>
            <AppButton type="button" variant="ghost" size="sm" icon-only aria-label="放大图片" title="放大" :disabled="zoom >= 3" @click="zoomIn"><Plus :size="16" /></AppButton>
            <AppButton type="button" variant="ghost" size="sm" icon-only aria-label="恢复适应窗口" title="恢复适应窗口" @click="resetZoom"><RotateCcw :size="15" /></AppButton>
            <AppButton type="button" variant="ghost" size="sm" icon-only aria-label="关闭大图" title="关闭" @click="emit('close')"><X :size="18" /></AppButton>
          </nav>
        </header>
        <div class="image-lightbox__stage">
          <img :src="src" :alt="alt" :style="{ transform: `scale(${zoom})` }" @click="toggleZoom" @load="onImageLoad" />
        </div>
        <p>点击图片可在适应窗口和 200% 之间切换</p>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.image-lightbox { position: fixed; inset: 0; z-index: 180; display: grid; grid-template-rows: auto minmax(0,1fr) auto; gap: 12px; padding: 18px; color: #f2f3f6; background: rgb(19 21 27 / 94%); backdrop-filter: blur(14px); }
.image-lightbox__toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.image-lightbox__toolbar > div,.image-lightbox__toolbar nav { display: flex; align-items: center; gap: 8px; }
.image-lightbox__toolbar > div { min-width: 0; color: #c8cbd3; font-size: 11px; font-variant-numeric: tabular-nums; }
.image-lightbox__toolbar nav { padding: 4px; border-radius: 12px; background: rgb(44 47 56 / 82%); }
.image-lightbox__toolbar :deep(.app-button) { color: #e7e9ef; }
.image-lightbox__toolbar :deep(.app-button:hover),.image-lightbox__toolbar :deep(.app-button:focus-visible) { color: #fff; background: rgb(255 255 255 / 10%); }
.image-lightbox__toolbar output { min-width: 46px; color: #d5d8df; font-size: 10px; text-align: center; font-variant-numeric: tabular-nums; }
.image-lightbox__stage { display: grid; min-width: 0; min-height: 0; place-items: center; overflow: auto; overscroll-behavior: contain; }
.image-lightbox__stage img { display: block; max-width: calc(100vw - 48px); max-height: calc(100dvh - 132px); object-fit: contain; cursor: zoom-in; transform-origin: center; transition: transform .22s cubic-bezier(.2,.72,.2,1); user-select: none; }
.image-lightbox__stage img[style*="scale(2"],.image-lightbox__stage img[style*="scale(3"] { cursor: zoom-out; }
.image-lightbox > p { margin: 0; color: #8f949f; font-size: 10px; text-align: center; }
.image-lightbox-enter-active,.image-lightbox-leave-active { transition: opacity .2s ease; }
.image-lightbox-enter-active .image-lightbox__stage img,.image-lightbox-leave-active .image-lightbox__stage img { transition: opacity .2s ease,transform .24s cubic-bezier(.2,.72,.2,1); }
.image-lightbox-enter-from,.image-lightbox-leave-to { opacity: 0; }
.image-lightbox-enter-from .image-lightbox__stage img,.image-lightbox-leave-to .image-lightbox__stage img { opacity: 0; transform: scale(.96) !important; }
@media (max-width: 640px) {
  .image-lightbox { padding: 10px; }
  .image-lightbox__toolbar { align-items: flex-start; flex-direction: column; }
  .image-lightbox__toolbar nav { align-self: flex-end; }
  .image-lightbox__stage img { max-width: calc(100vw - 20px); max-height: calc(100dvh - 164px); }
}
@media (prefers-reduced-motion: reduce) {
  .image-lightbox,.image-lightbox__stage img { transition-duration: .01ms !important; }
}
</style>
