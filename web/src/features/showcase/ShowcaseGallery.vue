<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ArrowLeft, ArrowRight, ArrowUpRight, Film, LoaderCircle, Play, X } from 'lucide-vue-next'
import { API_BASE, mediaUrl } from '@/api'
import { tr } from '@/i18n'
import type { ShowcaseWork } from '@/types'

const props = defineProps<{ works: ShowcaseWork[]; loading: boolean; error?: string }>()
const emit = defineEmits<{ retry: [] }>()
const category = ref('')
const categories = computed(() => [...new Set(props.works.map(work => work.category).filter(Boolean))])
const visibleWorks = computed(() => category.value ? props.works.filter(work => work.category === category.value) : props.works)
const ratios = ref<Record<string, string>>({})
const failedCovers = ref(new Set<string>())
const activeId = ref<string | null>(null)
const activeIndex = computed(() => visibleWorks.value.findIndex(work => work.id === activeId.value))
const activeWork = computed(() => visibleWorks.value[activeIndex.value])
const dialog = ref<HTMLDialogElement | null>(null)
const video = ref<HTMLVideoElement | null>(null)
const closeButton = ref<HTMLButtonElement | null>(null)
const buffering = ref(false), playbackFailed = ref(false), playbackRevision = ref(0)
let returnFocus: HTMLElement | null = null
let oldOverflow = '', scrollLocked = false

const sourceUrl = (path: string) => path.startsWith('/api/') ? API_BASE + path.slice(4) : mediaUrl(path)
const description = (work: ShowcaseWork) => /^(Agent|人工) 模式.*源剧本[：:]/.test(work.description) ? '' : work.description
function aspect(work: ShowcaseWork) {
  return ratios.value[work.id] || (work.cover_width && work.cover_height ? `${work.cover_width} / ${work.cover_height}` : '16 / 9')
}
function measure(event: Event, work: ShowcaseWork) {
  const image = event.target as HTMLImageElement
  if (image.naturalWidth && image.naturalHeight) ratios.value[work.id] = `${image.naturalWidth} / ${image.naturalHeight}`
}
function stopPlayback() { video.value?.pause() }
function selectWork(work: ShowcaseWork) {
  stopPlayback()
  activeId.value = work.id
  buffering.value = Boolean(work.video_url)
  playbackFailed.value = false
  playbackRevision.value = 0
}
async function openWork(work: ShowcaseWork, event: MouseEvent) {
  returnFocus = event.currentTarget instanceof HTMLElement ? event.currentTarget : null
  selectWork(work)
  await nextTick()
  if (!activeWork.value || !dialog.value) return
  if (!dialog.value.open) {
    oldOverflow = document.body.style.overflow
    scrollLocked = true
    document.body.style.overflow = 'hidden'
    dialog.value.showModal()
  }
  closeButton.value?.focus()
}
function finishClose() {
  stopPlayback()
  activeId.value = null
  if (scrollLocked) { document.body.style.overflow = oldOverflow; scrollLocked = false }
  if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true })
  returnFocus = null
}
function close() {
  stopPlayback()
  if (dialog.value?.open) dialog.value.close()
  finishClose()
}
function step(direction: number) {
  const next = visibleWorks.value[activeIndex.value + direction]
  if (next) selectWork(next)
}
function keydown(event: KeyboardEvent) {
  // Keep the native player's arrow-key seeking and volume controls intact.
  if (event.target instanceof HTMLElement && ['VIDEO', 'INPUT', 'SELECT', 'TEXTAREA'].includes(event.target.tagName)) return
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
  if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
    event.preventDefault()
    step(event.key === 'ArrowLeft' ? -1 : 1)
  }
}
function retryPlayback() {
  stopPlayback()
  playbackFailed.value = false
  buffering.value = true
  playbackRevision.value += 1
}
function mediaState(event: Event, state: 'ready' | 'waiting' | 'failed') {
  if (event.currentTarget !== video.value) return
  buffering.value = state === 'waiting'
  if (state === 'failed') playbackFailed.value = true
}
watch(() => props.works, () => {
  if (category.value && !categories.value.includes(category.value)) category.value = ''
  if (activeId.value && !activeWork.value) close()
})
onBeforeUnmount(close)
</script>

<template>
  <section class="showcase-gallery" :aria-label="tr('优秀作品')">
    <header class="gallery-heading"><h2>{{ tr('优秀作品') }}</h2><RouterLink to="/finished-library">{{ tr('查看作品库') }}<ArrowUpRight :size="14" aria-hidden="true" /></RouterLink></header>
    <div v-if="categories.length > 1" class="showcase-filters" role="group" :aria-label="tr('作品分类')"><button type="button" :aria-pressed="!category" @click="category = ''">{{ tr('全部作品') }}</button><button v-for="value in categories" :key="value" type="button" :aria-pressed="category === value" @click="category = value">{{ value }}</button></div>
    <div v-if="error" class="gallery-state" role="alert"><p>{{ error }}</p><button type="button" @click="emit('retry')">{{ tr('重新加载') }}</button></div>
    <div v-else-if="loading" class="gallery-loading" role="status"><span class="sr-only">{{ tr('正在加载作品…') }}</span><div v-for="index in 4" :key="index" class="gallery-skeleton" aria-hidden="true" /></div>
    <div v-else-if="!visibleWorks.length" class="gallery-state"><Film :size="28" aria-hidden="true" /><p>{{ tr('还没有公开作品。下一个画面，由你开始。') }}</p></div>
    <div v-else class="showcase-masonry">
      <button v-for="work in visibleWorks" :key="work.id" type="button" class="showcase-card" :aria-label="tr('播放作品：{p0}', { p0: work.title })" aria-haspopup="dialog" @click="openWork(work, $event)">
        <span class="work-visual" :style="{aspectRatio: aspect(work)}"><img v-if="work.cover && !failedCovers.has(work.id)" :src="sourceUrl(work.cover)" :alt="work.title" loading="lazy" decoding="async" @load="measure($event,work)" @error="failedCovers.add(work.id)"><span v-else class="cover-fallback"><Film :size="26" aria-hidden="true" />{{ tr('封面暂不可用') }}</span><span class="work-play" aria-hidden="true"><Play :size="22" fill="currentColor" /></span><span v-if="work.duration" class="work-duration">{{ work.duration }}</span></span>
        <span class="work-title">{{ work.title }}</span><span v-if="description(work) || work.category" class="work-description">{{ description(work) || work.category }}</span>
      </button>
    </div>
      <dialog ref="dialog" class="showcase-viewer" :aria-label="tr('作品播放器')" aria-labelledby="showcase-viewer-title" @cancel.prevent="close" @close="finishClose" @keydown="keydown">
        <template v-if="activeWork">
          <section class="viewer-stage" :aria-label="tr('视频播放区')">
            <button ref="closeButton" type="button" class="viewer-close viewer-control" :aria-label="tr('关闭播放器')" @click="close"><X :size="21" /></button>
            <button v-if="visibleWorks.length > 1" type="button" class="viewer-previous viewer-control" :disabled="activeIndex === 0" :aria-label="tr('上一个作品')" @click="step(-1)"><ArrowLeft :size="22" /></button>
            <div class="viewer-media" :aria-busy="buffering">
              <video v-if="activeWork.video_url && !playbackFailed" :key="`${activeWork.id}:${playbackRevision}`" ref="video" :src="sourceUrl(activeWork.video_url)" :poster="sourceUrl(activeWork.cover)" :aria-label="activeWork.title" controls autoplay playsinline preload="metadata" @loadeddata="mediaState($event,'ready')" @canplay="mediaState($event,'ready')" @playing="mediaState($event,'ready')" @waiting="mediaState($event,'waiting')" @error="mediaState($event,'failed')" />
              <div v-if="buffering && !playbackFailed" class="viewer-loading" role="status"><LoaderCircle :size="24" aria-hidden="true" /><span>{{ tr('正在加载视频…') }}</span></div>
              <div v-if="playbackFailed || !activeWork.video_url" class="viewer-unavailable" role="alert"><Film :size="32" aria-hidden="true" /><p>{{ playbackFailed ? tr('视频暂时无法播放，请重试。') : tr('当前作品暂无可播放的视频。') }}</p><button v-if="activeWork.video_url" type="button" @click="retryPlayback">{{ tr('重新加载视频') }}</button></div>
            </div>
            <button v-if="visibleWorks.length > 1" type="button" class="viewer-next viewer-control" :disabled="activeIndex === visibleWorks.length - 1" :aria-label="tr('下一个作品')" @click="step(1)"><ArrowRight :size="22" /></button>
          </section>
          <aside class="viewer-information">
            <header><img v-if="activeWork.cover && !failedCovers.has(activeWork.id)" :src="sourceUrl(activeWork.cover)" alt="" @error="failedCovers.add(activeWork.id)"><div><h2 id="showcase-viewer-title">{{ activeWork.title }}</h2><p v-if="activeWork.category">{{ activeWork.category }}</p></div></header>
            <section class="viewer-introduction"><h3>{{ tr('作品介绍') }}</h3><p>{{ description(activeWork) || tr('暂无作品介绍') }}</p></section>
            <p v-if="activeWork.author" class="viewer-author">{{ activeWork.author }}</p>
            <RouterLink v-if="activeWork.novel_id && activeWork.episodes_count > 1" :to="`/works/${activeWork.novel_id}`" class="viewer-series" @click="close">{{ tr('查看全部 {p0} 集', { p0: activeWork.episodes_count }) }}<ArrowUpRight :size="14" aria-hidden="true" /></RouterLink>
          </aside>
        </template>
      </dialog>
  </section>
</template>

<style scoped>
.showcase-gallery { margin-top: 34px; color: var(--app-text); }
.gallery-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 20px; }.gallery-heading h2 { margin: 0; font-size: 20px; font-weight: 650; }.gallery-heading a { display: inline-flex; align-items: center; gap: 6px; color: var(--app-text-secondary); font-size: 12px; min-height: 40px; }
.showcase-filters { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 18px; }.showcase-filters button { border: 0; border-radius: 18px; padding: 8px 13px; color: var(--app-text-secondary); background: transparent; cursor: pointer; }.showcase-filters button[aria-pressed='true'] { color: var(--app-text); background: var(--app-surface-hover); }
.showcase-masonry { columns: 4; column-gap: 20px; }.showcase-card { display: block; break-inside: avoid; width: 100%; margin: 0 0 22px; padding: 0; border: 0; background: transparent; text-align: left; color: inherit; cursor: pointer; font: inherit; }
.work-visual { position: relative; display: block; width: 100%; overflow: hidden; border-radius: 11px; background: var(--app-surface-muted); }.work-visual img { display: block; width: 100%; height: 100%; object-fit: contain; }.work-duration { position: absolute; right: 8px; bottom: 8px; padding: 2px 6px; color: #fff; background: rgb(0 0 0 / 65%); border-radius: 4px; font-size: 11px; line-height: 1.6; }
.work-title { display: block; margin-top: 10px; font-size: 14px; font-weight: 550; line-height: 1.5; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.work-description { display: block; margin-top: 3px; font-size: 12px; line-height: 1.5; color: var(--app-text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.work-play { position: absolute; inset: 0; display: grid; place-items: center; color: #fff; background: rgb(0 0 0 / 15%); opacity: 0; transition: opacity .18s; }.showcase-card:hover .work-play, .showcase-card:focus-visible .work-play { opacity: 1; }.showcase-card:hover .work-title { color: var(--app-accent); }
.cover-fallback { display: flex; align-items: center; justify-content: center; flex-direction: column; height: 100%; gap: 8px; color: var(--app-text-muted); font-size: 11px; }
.gallery-state { display: flex; justify-content: center; align-items: center; gap: 14px; min-height: 140px; color: var(--app-text-secondary); font-size: 13px; }.gallery-state button, .viewer-unavailable button { border: 0; padding: 10px 16px; border-radius: 8px; background: var(--app-surface-hover); color: var(--app-text); cursor: pointer; }
.gallery-loading { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 20px; }.gallery-skeleton { aspect-ratio: 16/9; border-radius: 11px; background: var(--app-surface-muted); }
.showcase-viewer { position: fixed; inset: 0; width: 100vw; height: 100dvh; max-width: none; max-height: none; margin: 0; padding: 0; border: 0; outline: none; background: var(--app-canvas); color: var(--app-text); overflow: hidden; }.showcase-viewer[open] { display: grid; grid-template-columns: minmax(0,1fr) 340px; }.showcase-viewer::backdrop { background: var(--app-canvas); }
.viewer-stage { position: relative; display: flex; align-items: center; justify-content: center; min-width: 0; min-height: 0; padding: 72px 70px; background: var(--app-canvas); }.viewer-media { display: grid; position: relative; width: 100%; height: 100%; min-width: 0; min-height: 0; place-items: center; }.viewer-media video { display: block; width: 100%; height: 100%; max-height: calc(100dvh - 144px); object-fit: contain; border-radius: 9px; background: transparent; }
.viewer-control { position: absolute; z-index: 2; display: grid; place-items: center; width: 44px; height: 44px; padding: 0; border: 0; border-radius: 50%; color: var(--app-text-secondary); background: var(--app-surface); cursor: pointer; transition: background .15s,color .15s; }.viewer-control:hover:not(:disabled) { color: var(--app-text); background: var(--app-surface-hover); }.viewer-control:disabled { opacity: .3; cursor: default; }.viewer-close { top: 16px; right: 16px; background: transparent; }.viewer-previous { left: 12px; top: calc(50% - 22px); }.viewer-next { right: 12px; top: calc(50% - 22px); }
.viewer-information { padding: 32px 26px; background: var(--app-surface); overflow-y: auto; min-width: 0; }.viewer-information header { display: flex; align-items: flex-start; gap: 13px; }.viewer-information header img { flex: 0 0 56px; width: 56px; height: 56px; border-radius: 10px; object-fit: cover; }.viewer-information h2 { margin: 0; font-size: 18px; font-weight: 600; line-height: 1.5; overflow-wrap: anywhere; }.viewer-information header p { margin: 5px 0 0; color: var(--app-text-muted); font-size: 12px; }.viewer-introduction { margin-top: 30px; }.viewer-introduction h3 { margin: 0 0 12px; font-size: 13px; font-weight: 400; color: var(--app-text-muted); }.viewer-introduction p { margin: 0; font-size: 13px; line-height: 1.95; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--app-text-secondary); }.viewer-author { margin: 30px 0 0; color: var(--app-text-secondary); font-size: 12px; }.viewer-series { display: inline-flex; align-items: center; gap: 7px; margin-top: 26px; color: var(--app-accent); font-size: 12px; min-height: 44px; }
.viewer-loading, .viewer-unavailable { position: absolute; inset: 0; display: flex; flex-direction: column; justify-content: center; align-items: center; gap: 12px; color: var(--app-text-secondary); font-size: 13px; }.viewer-loading { pointer-events: none; }.viewer-loading svg { animation: viewer-spin 1s linear infinite; }.viewer-loading span { padding: 5px 10px; border-radius: 6px; background: var(--app-surface); }.viewer-unavailable { background: var(--app-surface-muted); border-radius: 9px; text-align: center; padding: 20px; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }button:focus-visible,a:focus-visible { outline: 2px solid var(--app-accent); outline-offset: 3px; }
@keyframes viewer-spin { to { transform: rotate(360deg); } }
@media(max-width:1100px) { .showcase-masonry { columns: 3; }.gallery-loading { grid-template-columns: repeat(3,minmax(0,1fr)); }.showcase-viewer[open] { grid-template-columns: minmax(0,1fr) 300px; }.viewer-stage { padding: 64px 54px; }.viewer-previous { left: 6px; }.viewer-next { right: 6px; }.viewer-information { padding: 28px 20px; } }
@media(max-width:760px) { .viewer-close { position: fixed; top: 10px; right: 10px; background: var(--app-surface); }.showcase-masonry { columns: 2; column-gap: 14px; }.gallery-loading { grid-template-columns: repeat(2,minmax(0,1fr)); }.showcase-viewer[open] { display: flex; flex-direction: column; overflow-y: auto; }.viewer-stage { flex: 0 0 62dvh; padding: 58px 45px 20px; }.viewer-media video { max-height: calc(62dvh - 78px); }.viewer-information { overflow: visible; padding: 22px; flex: 1; }.viewer-information h2 { font-size: 16px; }.viewer-introduction { margin-top: 22px; }.work-title { font-size: 13px; }.work-description { font-size: 11px; } }
@media(max-width:380px) { .showcase-masonry { columns: 1; } }
@media(prefers-reduced-motion:reduce) { .work-play,.viewer-control { transition: none; }.viewer-loading svg { animation: none; } }
</style>
