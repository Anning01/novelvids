<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight, Minus, Plus, RotateCcw, X } from 'lucide-vue-next'
import { tr } from '@/i18n'
import type { PreviewImage } from '@/shared/imageGallery'

const props = withDefaults(defineProps<{
  open: boolean
  src: string
  alt: string
  format?: string
  images?: PreviewImage[]
  animated?: boolean
}>(), { format: '', images: () => [] })
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement | null>(null)
const track = ref<HTMLElement | null>(null)
const slides = ref<PreviewImage[]>([])
const index = ref(0)
const zoom = ref(1)
const loaded = ref<Record<string, string>>({})
const failed = ref<Record<string, boolean>>({})
let scrollTimer: ReturnType<typeof setTimeout> | undefined
let resize: ResizeObserver | undefined
const current = computed(() => slides.value[index.value])
const metadata = computed(() => {
  const item = current.value
  const format = item?.format || item?.src.match(/^data:image\/([^;,]+)/i)?.[1]
    || item?.src.split(/[?#]/, 1)[0]?.match(/\.([a-z0-9]+)$/i)?.[1] || 'IMAGE'
  return [item && loaded.value[item.src], format.toUpperCase().replace('JPG', 'JPEG')].filter(Boolean).join(' / ')
})
function align() {
  if (track.value) track.value.scrollLeft = index.value * track.value.clientWidth
}
function select(next: number) {
  if (next < 0 || next >= slides.value.length) return
  index.value = next
  zoom.value = 1
  align()
}
watch(index, async () => {
  await nextTick()
  dialog.value?.querySelector<HTMLElement>('[aria-current="true"]')?.scrollIntoView({block: 'nearest', inline: 'nearest'})
})
function settleScroll() {
  clearTimeout(scrollTimer)
  scrollTimer = setTimeout(() => {
    if (!track.value?.clientWidth) return
    const next = Math.round(track.value.scrollLeft / track.value.clientWidth)
    if (next !== index.value) select(next)
  }, 120)
}
function keydown(event: KeyboardEvent) {
  // The parent asset editor also handles Escape; let the native dialog own dismissal.
  event.stopPropagation()
  if (event.target instanceof HTMLElement && event.target.closest('input,textarea,select,[contenteditable="true"]')) return
  if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
    event.preventDefault()
    select(index.value + (event.key === 'ArrowLeft' ? -1 : 1))
  }
}
function load(event: Event, item: PreviewImage) {
  const image = event.currentTarget as HTMLImageElement
  loaded.value[item.src] = `${image.naturalWidth} × ${image.naturalHeight}`
}
async function close() {
  const panel = dialog.value
  if (!panel?.open || panel.hasAttribute('data-closing')) return
  if (props.animated && typeof panel.getAnimations === 'function') {
    // Keep the native dialog in the top layer until its exit finishes.
    panel.setAttribute('data-closing', '')
    await Promise.allSettled(panel.getAnimations({ subtree: true }).map(animation => animation.finished))
    panel.removeAttribute('data-closing')
  }
  panel.close()
}
function cancel(event: Event) {
  if (!props.animated) return
  event.preventDefault()
  void close()
}
watch(() => [props.open, props.src] as const, async ([open]) => {
  await nextTick()
  if (!dialog.value) return
  if (!open) { dialog.value.close(); return }
  // Freeze the browsing sequence while open: background generations must not move the current slide.
  slides.value = props.images.filter(item => item.src)
  if (!slides.value.some(item => item.src === props.src) && props.src) {
    slides.value = [{ src: props.src, alt: props.alt, format: props.format }, ...slides.value]
  }
  index.value = Math.max(0, slides.value.findIndex(item => item.src === props.src))
  zoom.value = 1
  await nextTick()
  if (!props.open || !dialog.value) return
  if (!dialog.value.open) dialog.value.showModal()
  align()
  resize?.disconnect()
  if (track.value) { resize = new ResizeObserver(align); resize.observe(track.value) }
}, { immediate: true })
onBeforeUnmount(() => { clearTimeout(scrollTimer); resize?.disconnect(); dialog.value?.close() })
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" class="image-lightbox" :class="{ 'is-animated': animated }" :aria-label="tr('图片放大查看')"
      @keydown="keydown" @cancel="cancel" @close="emit('close')">
      <template v-if="open">
        <header class="image-lightbox__toolbar">
          <div class="image-lightbox__heading">
            <strong>{{ current?.alt || alt }}</strong>
            <span>{{ metadata }}</span>
          </div>
          <nav :aria-label="tr('图片缩放控制')">
            <button type="button" :aria-label="tr('缩小图片')" :disabled="zoom <= 0.5" @click="zoom = Math.max(0.5, zoom - .25)"><Minus :size="18" /></button>
            <output>{{ Math.round(zoom * 100) }}%</output>
            <button type="button" :aria-label="tr('放大图片')" :disabled="zoom >= 3" @click="zoom = Math.min(3, zoom + .25)"><Plus :size="18" /></button>
            <button type="button" :aria-label="tr('恢复适应窗口')" @click="zoom = 1"><RotateCcw :size="18" /></button>
            <button type="button" autofocus :aria-label="tr('关闭大图')" @click="close"><X :size="22" /></button>
          </nav>
        </header>
        <div class="image-lightbox__viewport">
          <div ref="track" class="image-lightbox__track" :class="{ 'is-zoomed': zoom > 1 }" @scroll.passive="settleScroll">
            <div v-for="(item, position) in slides" :key="`${position}:${item.src}`" class="image-lightbox__stage" :class="{ 'is-zoomed': position === index && zoom > 1 }"
              role="group" :aria-label="`${position + 1} / ${slides.length} · ${item.alt}`" :inert="position !== index ? true : undefined">
              <p v-if="failed[item.src]" role="status">{{ slides.length > 1 ? tr('图片加载失败，可切换其他图片') : tr('图片加载失败，请检查图片是否仍可访问') }}</p>
              <template v-else-if="Math.abs(position - index) <= 1">
                <span v-if="!loaded[item.src]" class="image-lightbox__loading">{{ tr('正在加载图片…') }}</span>
                <img :src="item.src" :alt="item.alt" :style="{ transform: `scale(${position === index ? zoom : 1})` }" draggable="false"
                  @click="zoom = zoom === 1 ? 2 : 1" @load="load($event, item)" @error="failed[item.src] = true" />
              </template>
            </div>
          </div>
          <template v-if="slides.length > 1">
            <button type="button" class="image-lightbox__previous" :aria-label="tr('上一张')" :disabled="index === 0" @click="select(index - 1)"><ChevronLeft :size="28" /></button>
            <button type="button" class="image-lightbox__next" :aria-label="tr('下一张')" :disabled="index === slides.length - 1" @click="select(index + 1)"><ChevronRight :size="28" /></button>
          </template>
        </div>
        <footer class="image-lightbox__footer">
          <div role="status" aria-live="polite" aria-atomic="true">{{ index + 1 }} / {{ slides.length }} · {{ current?.alt }}</div>
          <nav v-if="slides.length > 1" class="image-lightbox__positions" :aria-label="tr('选择预览图片')">
            <button v-for="(item, position) in slides" :key="position" type="button" :aria-label="`${position + 1} · ${item.alt}`"
              :aria-current="position === index ? 'true' : undefined" @click="select(position)">{{ item.label || position + 1 }}</button>
          </nav>
          <small>{{ slides.length > 1 ? tr('左右滑动或按 ← → 切换，点击图片放大，Esc 关闭') : tr('点击图片可在适应窗口和 200% 之间切换') }}</small>
        </footer>
      </template>
    </dialog>
  </Teleport>
</template>

<style scoped>
.image-lightbox { position: fixed; inset: 0; width: 100%; max-width: none; height: 100dvh; max-height: none; margin: 0; padding: 16px; box-sizing: border-box; overflow: hidden; border: 0; color: #f2f3f6; background: #13151b; }
.image-lightbox[open] { display: grid; grid-template-rows: auto minmax(0,1fr) auto; gap: 12px; }
.image-lightbox:modal { overscroll-behavior: contain; }
.image-lightbox::backdrop { background: #13151b; overflow: hidden; overscroll-behavior: contain; }
.image-lightbox__toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.image-lightbox__heading { display: grid; gap: 4px; min-width: 0; }
.image-lightbox__heading strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }
.image-lightbox__heading span,.image-lightbox__footer small { color: #b8bdc9; font-size: 12px; }
.image-lightbox nav { display: flex; align-items: center; gap: 4px; }
.image-lightbox button { display: inline-grid; place-items: center; flex-shrink: 0; min-width: 44px; min-height: 44px; padding: 8px; border: 1px solid #4a4f5b; border-radius: 8px; color: inherit; background: #282d37; cursor: pointer; font: inherit; touch-action: manipulation; }
.image-lightbox button:hover:not(:disabled) { background: #3a4353; }
.image-lightbox button:focus-visible { outline: 2px solid #fff; outline-offset: 2px; }
.image-lightbox button:disabled { opacity: .35; cursor: default; }
.image-lightbox output { min-width: 45px; text-align: center; font-size: 12px; font-variant-numeric: tabular-nums; }
.image-lightbox__viewport { position: relative; min-width: 0; min-height: 0; }
.image-lightbox__track { display: flex; height: 100%; overflow-x: auto; scroll-snap-type: x mandatory; overscroll-behavior: contain; scrollbar-width: none; }
.image-lightbox__track.is-zoomed { overflow-x: hidden; }
.image-lightbox__stage { position: relative; flex: 0 0 100%; height: 100%; display: grid; grid-template-rows: minmax(0,1fr); place-items: center; min-width: 0; min-height: 0; overflow: hidden; scroll-snap-align: start; scroll-snap-stop: always; }
.image-lightbox__stage.is-zoomed { place-items: start; overflow: auto; overscroll-behavior: contain; }
.image-lightbox__stage img { display: block; max-width: 100%; max-height: 100%; object-fit: contain; cursor: zoom-in; transform-origin: center; user-select: none; }
.image-lightbox__stage.is-zoomed img { transform-origin: top left; cursor: zoom-out; }
.image-lightbox__loading { position: absolute; color: #b8bdc9; }
.image-lightbox__previous,.image-lightbox__next { position: absolute; top: 50%; transform: translateY(-50%); }
.image-lightbox__previous { left: 8px; }.image-lightbox__next { right: 8px; }
.image-lightbox__footer { display: grid; justify-items: center; gap: 6px; min-width: 0; font-size: 13px; }
.image-lightbox__positions { max-width: 100%; overflow-x: auto; padding: 3px; scrollbar-width: thin; scrollbar-color: #555d6d #20252e; }
.image-lightbox__positions button { min-width: 36px; min-height: 36px; font-size: 12px; }
.image-lightbox__positions button[aria-current] { color: #13151b; background: #f2f3f6; }
@media (max-width: 640px) {
  .image-lightbox { padding: 10px; }
  .image-lightbox__toolbar { flex-wrap: wrap; gap: 8px; }
  .image-lightbox__heading { flex: 1 1 100%; }
  .image-lightbox__toolbar nav { margin-left: auto; }
  .image-lightbox__footer small { text-align: center; }
}
</style>

<style>
.image-lightbox.is-animated {
  opacity: 0;
  transition: opacity 140ms ease-out;
}
.image-lightbox.is-animated::backdrop {
  background-color: transparent;
  transition: background-color 140ms ease-out;
}
.image-lightbox.is-animated[open]:not([data-closing]) {
  opacity: 1;
  transition-duration: 220ms;
}
.image-lightbox.is-animated[open]:not([data-closing])::backdrop {
  background-color: rgb(15 17 23 / 38%);
  transition-duration: 220ms;
}
@starting-style {
  .image-lightbox.is-animated[open]:not([data-closing]) { opacity: 0; }
  .image-lightbox.is-animated[open]:not([data-closing])::backdrop { background-color: transparent; }
}
@media (prefers-reduced-motion: no-preference) {
  .image-lightbox.is-animated .image-lightbox__viewport {
    scale: .965;
    transition: scale 140ms ease-out;
  }
  .image-lightbox.is-animated[open]:not([data-closing]) .image-lightbox__viewport {
    scale: 1;
    transition: scale 220ms cubic-bezier(.16, 1, .3, 1);
  }
  @starting-style {
    .image-lightbox.is-animated[open]:not([data-closing]) .image-lightbox__viewport { scale: .965; }
  }
}
</style>
