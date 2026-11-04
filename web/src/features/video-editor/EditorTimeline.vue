<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Film, Music2, Type, Sticker, Plus, Scissors, Trash2, Undo2, Redo2, Copy, ZoomIn, ZoomOut } from 'lucide-vue-next'
import { mediaUrl } from '@/api'
import { tr } from '@/i18n'
import VideoThumbnail from '@/components/VideoThumbnail.vue'
import { clipsInRect, type ClipRect, type SelectionRect } from './timelineSelection'
import { clipTitle, frameTime, kindLabel, moveClip, orderedVideos, resizeClip, snapAudioStart, sourceKey, totalDuration } from './model'
import type { ClipKind, EditClip, EditDocument, EditorMedia, VideoClip } from './types'
const props = defineProps<{ document: EditDocument; media: EditorMedia[]; time: number; selectedId: string; selectedIds?: string[]; readOnly: boolean; canUndo: boolean; canRedo: boolean }>()
const emit = defineEmits<{ select: [id: string]; selectMany: [ids: string[]]; seek: [time: number]; move: [id: string, start: number]; edge: [id: string, side: 'left' | 'right', delta: number]; add: [kind: ClipKind]; split: []; remove: []; duplicate: []; undo: []; redo: [] }>()
const marquee = ref<SelectionRect | null>(null), marqueeIds = ref<string[] | null>(null)
const selectedSet = computed(() => new Set(marqueeIds.value ?? props.selectedIds ?? (props.selectedId ? [props.selectedId] : [])))
const AUDIO_SNAP_DISTANCE_PX = 8
const zoom = ref(24), viewport = ref<HTMLElement | null>(null), dragging = ref<EditClip | null>(null)
const videoPreview = ref<VideoClip[]>([])
const previewVideosById = computed(() => new Map(videoPreview.value.map(clip => [clip.id, clip])))
const canvas = ref<HTMLElement | null>(null), labels = ref<HTMLElement | null>(null)
function trackWidth() { return (viewport.value?.clientWidth ?? 0) - (labels.value?.offsetWidth ?? 0) }
const indexed = computed(() => new Map(props.media.map(item => [item.key, item])))
const width = computed(() => Math.max(trackWidth() || 800, (Math.max(totalDuration(props.document), dragging.value ? dragging.value.start + dragging.value.duration : 0, ...videoPreview.value.map(clip => clip.start + clip.duration)) + 5) * zoom.value))
const ticks = computed(() => Array.from({ length: Math.ceil(width.value / zoom.value / 5) + 1 }, (_, i) => i * 5))
const tracks = computed(() => (['sticker', 'subtitle', 'video', 'audio'] as ClipKind[]).map(kind => {
  const items = props.document.clips.filter(c => c.type === kind).sort((a, b) => a.start - b.start)
  const ends: number[] = [], positions = new Map<string, number>()
  const layout = kind === 'audio' && dragging.value?.type === 'audio'
    ? items.map(previewClip).sort((a, b) => a.start - b.start)
    : items
  for (const clip of layout) {
    let lane = ends.findIndex(end => end <= clip.start + .001)
    if (lane < 0) lane = ends.length
    ends[lane] = clip.start + clip.duration
    positions.set(clip.id, lane)
  }
  const laneHeight = kind === 'video' ? 66 : kind === 'audio' ? 48 : 36
  const laneCount = Math.max(1, ends.length)
  return { kind, items, positions, laneHeight, laneCount, height: laneCount * laneHeight + 8, icon: { video: Film, audio: Music2, subtitle: Type, sticker: Sticker }[kind] }
}))
let cleanup: (() => void) | null = null
function format(value: number) { return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(Math.floor(value % 60)).padStart(2, '0')}` }
function seek(event: PointerEvent) {
  const el = canvas.value
  if (!el || event.button !== 0) return
  event.preventDefault(); cleanup?.()
  const move = (current: PointerEvent) => {
    if (current.pointerId !== event.pointerId) return
    const time = (current.clientX - el.getBoundingClientRect().left) / zoom.value
    emit('seek', Math.min(totalDuration(props.document), Math.max(0, time)))
  }
  const stop = (current: PointerEvent) => {
    if (current.pointerId !== event.pointerId) return
    if (current.type === 'pointerup') move(current)
    cleanup?.()
  }
  cleanup = () => {
    window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stop)
    window.removeEventListener('pointercancel', stop); cleanup = null
  }
  move(event)
  window.addEventListener('pointermove', move); window.addEventListener('pointerup', stop)
  window.addEventListener('pointercancel', stop)
}
function chooseClip(event: MouseEvent, clip: EditClip) {
  const current = props.selectedIds ?? (props.selectedId ? [props.selectedId] : [])
  if (event.shiftKey) {
    const anchor = props.document.clips.find(item => item.id === props.selectedId)
    if (anchor?.type === clip.type) {
      const ordered = props.document.clips.filter(item => item.type === clip.type).sort((a, b) => a.start - b.start)
      const a = ordered.findIndex(item => item.id === anchor.id), b = ordered.findIndex(item => item.id === clip.id)
      emit('selectMany', [...new Set([...current, ...ordered.slice(Math.min(a,b), Math.max(a,b)+1).map(item => item.id)])])
      return
    }
  }
  if (event.shiftKey || event.metaKey || event.ctrlKey) {
    emit('selectMany', current.includes(clip.id) ? current.filter(id => id !== clip.id) : [...current, clip.id])
  } else emit('select', clip.id)
}
function startMarquee(event: PointerEvent) {
  if (event.button !== 0 || !(event.target instanceof Element) || event.target.closest('.editor-track-clip,.editor-time-ruler,.editor-playhead')) return
  const el = canvas.value
  if (!el) return
  event.preventDefault(); cleanup?.()
  const initial = props.selectedIds ?? (props.selectedId ? [props.selectedId] : [])
  const additive = event.shiftKey || event.metaKey || event.ctrlKey
  const rect = el.getBoundingClientRect(), origin = { x: event.clientX - rect.left, y: event.clientY - rect.top }
  const geometry: ClipRect[] = []
  let top = 28
  for (const track of tracks.value) {
    for (const clip of track.items) {
      const left = clip.start * zoom.value, y = top + 4 + (track.positions.get(clip.id) || 0) * track.laneHeight
      geometry.push({ id: clip.id, left, right: left + Math.max(12, clip.duration * zoom.value - 2), top: y, bottom: y + track.laneHeight - 4 })
    }
    top += track.height
  }
  let frame = 0, latest = event, moved = false, scrolling = true
  const update = () => {
    frame = 0
    const view = viewport.value
    let scrolled = false
    if (scrolling && view && view.clientWidth && view.clientHeight) {
      const bounds = view.getBoundingClientRect(), beforeX = view.scrollLeft, beforeY = view.scrollTop
      const dx = latest.clientX > bounds.left+view.clientWidth-24 ? 16 : latest.clientX < bounds.left+(labels.value?.offsetWidth || 0)+24 ? -16 : 0
      const dy = latest.clientY > bounds.top+view.clientHeight-24 ? 12 : latest.clientY < bounds.top+24 ? -12 : 0
      if (dx) view.scrollLeft += dx
      if (dy) view.scrollTop += dy
      scrolled = beforeX !== view.scrollLeft || beforeY !== view.scrollTop
    }
    const bounds = el.getBoundingClientRect()
    const x = latest.clientX - bounds.left, y = latest.clientY - bounds.top
    if (Math.hypot(x-origin.x,y-origin.y)>3) moved = true
    if (!moved) return
    marquee.value = { left: Math.min(origin.x,x), right: Math.max(origin.x,x), top: Math.min(origin.y,y), bottom: Math.max(origin.y,y) }
    const hits = clipsInRect(geometry, marquee.value)
    marqueeIds.value = additive ? [...new Set([...initial, ...hits])] : hits
    if (scrolled) frame = requestAnimationFrame(update)
  }
  const move = (current: PointerEvent) => {
    if (current.pointerId !== event.pointerId) return
    latest = current
    if (!frame) frame = requestAnimationFrame(update)
  }
  const stop = (current: PointerEvent) => {
    if (current.pointerId !== event.pointerId) return
    cancelAnimationFrame(frame); frame = 0; scrolling = false
    if (current.type === 'pointerup') {
      latest = current; update()
      emit('selectMany', moved ? marqueeIds.value || [] : additive ? initial : [])
    }
    cleanup?.()
  }
  cleanup = () => {
    cancelAnimationFrame(frame); marquee.value = null; marqueeIds.value = null
    window.removeEventListener('pointermove',move); window.removeEventListener('pointerup',stop); window.removeEventListener('pointercancel',stop); cleanup = null
  }
  window.addEventListener('pointermove',move); window.addEventListener('pointerup',stop); window.addEventListener('pointercancel',stop)
}
function drag(event: PointerEvent, clip: EditClip, edge?: 'left' | 'right') {
  if (event.button !== 0) return
  chooseClip(event, clip)
  if (props.readOnly || event.shiftKey || event.metaKey || event.ctrlKey) return
  event.preventDefault()
  if (event.currentTarget instanceof HTMLElement) event.currentTarget.focus({ preventScroll: true })
  cleanup?.(); const x = event.clientX, scroll = viewport.value?.scrollLeft || 0
  let delta = 0, targetStart = clip.start, moved = false
  const move = (current: PointerEvent) => {
    if (current.pointerId !== event.pointerId) return
    const distance = current.clientX - x + (viewport.value?.scrollLeft || 0) - scroll
    delta = distance / zoom.value
    if (Math.abs(distance) > 3) moved = true
    if (!moved) return
    if (edge) {
      const item = 'source' in clip ? indexed.value.get(sourceKey(clip.source)) : undefined
      try {
        const result = resizeClip(props.document, clip.id, edge, delta, item)
        dragging.value = result.clips.find(item => item.id === clip.id) ?? null
        if (clip.type === 'video') videoPreview.value = orderedVideos(result)
      } catch { /* Keep the last valid preview; the workspace reports invalid drops. */ }
    } else if (clip.type === 'video') {
      targetStart = clip.start + delta
      videoPreview.value = orderedVideos(moveClip(props.document, clip.id, targetStart))
      dragging.value = previewVideosById.value.get(clip.id) ?? null
    } else {
      const start = Math.max(0, clip.start + delta)
      const snapped = clip.type === 'audio'
        ? snapAudioStart(clip, start, props.document.clips, AUDIO_SNAP_DISTANCE_PX / zoom.value)
        : start
      dragging.value = { ...clip, start: frameTime(snapped, props.document.fps) }
    }
  }
  const stop = (current: PointerEvent) => {
    if (current.pointerId !== event.pointerId) return
    if (current.type === 'pointerup') {
      move(current)
      if (moved && edge) emit('edge', clip.id, edge, delta)
      else if (moved && dragging.value) emit('move', clip.id, clip.type === 'video' ? targetStart : dragging.value.start)
    }
    cleanup?.()
  }
  cleanup = () => {
    window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stop)
    window.removeEventListener('pointercancel', stop); dragging.value = null; videoPreview.value = []; cleanup = null
  }
  window.addEventListener('pointermove', move); window.addEventListener('pointerup', stop)
  window.addEventListener('pointercancel', stop)
}
function nudgeClip(clip: EditClip, direction: -1 | 1) {
  if (props.readOnly) return
  if (clip.type !== 'video') {
    emit('move', clip.id, Math.max(0, clip.start + direction / props.document.fps))
    return
  }
  const videos = orderedVideos(props.document)
  const neighbor = videos[videos.findIndex(item => item.id === clip.id) + direction]
  if (neighbor) emit('move', clip.id, clip.start + direction * neighbor.duration)
}
function previewClip(clip: EditClip) {
  return previewVideosById.value.get(clip.id) ?? (dragging.value?.id === clip.id ? dragging.value : clip)
}
function clipStyle(clip: EditClip, lane: number, laneHeight: number) {
  const preview = previewClip(clip)
  return { left: `${clip.start * zoom.value}px`, transform: preview.start !== clip.start ? `translateX(${(preview.start - clip.start) * zoom.value}px)` : '', width: `${Math.max(12, preview.duration * zoom.value - 2)}px`, top: `${4 + lane * laneHeight}px`, height: `${laneHeight - 4}px` }
}
function poster(clip: EditClip) { return 'source' in clip ? mediaUrl(indexed.value.get(sourceKey(clip.source))?.poster || (clip.type === 'sticker' ? indexed.value.get(sourceKey(clip.source))?.url : '')) : '' }
function filmstripStyle(clip: EditClip) { return { backgroundImage: `url(${JSON.stringify(poster(clip))})` } }
function fit() { if (viewport.value) zoom.value = Math.min(300, Math.max(8, (trackWidth() - 12) / Math.max(1, totalDuration(props.document)))) }
function reveal() {
  const el = viewport.value; if (!el) return
  const x = props.time * zoom.value
  const width = trackWidth()
  if (x > el.scrollLeft + width - 40 || x < el.scrollLeft) el.scrollLeft = Math.max(0, x - width * .4)
}
watch([() => props.selectedId, () => tracks.value.map(track => `${track.height}:${track.positions.get(props.selectedId) ?? ''}`).join('|')], () => {
  const el = viewport.value
  const clip = canvas.value?.querySelector('.editor-track-clip.selected')
  if (!el || !clip || !el.clientHeight) return
  const bounds = el.getBoundingClientRect(), item = clip.getBoundingClientRect()
  if (!item.width || !item.height) return
  const visibleLeft = bounds.left + (labels.value?.offsetWidth ?? 0)
  const visibleRight = bounds.left + el.clientWidth
  if (item.right <= visibleLeft || item.left >= visibleRight) el.scrollLeft += item.left - visibleLeft
  if (item.top < bounds.top) el.scrollTop += item.top - bounds.top
  else if (item.bottom > bounds.top + el.clientHeight) el.scrollTop += item.bottom - bounds.top - el.clientHeight
}, { flush: 'post' })
onMounted(fit); onBeforeUnmount(() => cleanup?.())
defineExpose({ reveal })
</script>
<template>
  <section class="editor-timeline video-timeline" :aria-label="tr('多轨时间线')">
    <header class="editor-timeline-toolbar"><div class="editor-editing-tools"><button class="editor-icon-btn" :disabled="readOnly || !canUndo" :aria-label="tr('撤销')" @click="emit('undo')"><Undo2 :size="17" /></button><button class="editor-icon-btn" :disabled="readOnly || !canRedo" :aria-label="tr('重做')" @click="emit('redo')"><Redo2 :size="17" /></button><i></i><button class="editor-icon-btn" :disabled="readOnly || !selectedId || selectedSet.size>1" :aria-label="tr('在播放头处分割')" @click="emit('split')"><Scissors :size="17" /></button><button class="editor-icon-btn" :disabled="readOnly || !selectedId || selectedSet.size>1" :aria-label="tr('复制片段')" :title="tr('复制片段（⌘D / Ctrl+D）')" aria-keyshortcuts="Meta+D Control+D" @click="emit('duplicate')"><Copy :size="16" /></button><button class="editor-icon-btn" :disabled="readOnly || !selectedId" :aria-label="tr('移除片段')" :title="tr('移除片段（Delete / ⌫）')" aria-keyshortcuts="Delete Backspace" @click="emit('remove')"><Trash2 :size="16" /></button><span>{{ tr('本集时间线') }}</span></div><div class="editor-zoom"><button class="editor-icon-btn" :aria-label="tr('缩小时间线')" @click="zoom = Math.max(8, zoom - 4)"><ZoomOut :size="16" /></button><input v-model.number="zoom" type="range" min="8" max="300" :aria-label="tr('时间轴刻度尺寸')" /><button class="editor-icon-btn" :aria-label="tr('放大时间线')" @click="zoom = Math.min(300, zoom + 4)"><ZoomIn :size="16" /></button><button class="editor-link" @click="fit">{{ tr('适应') }}</button></div></header>
    <div ref="viewport" class="editor-track-body editor-timeline-scroll">
      <div ref="labels" class="editor-track-labels">
        <div class="editor-ruler-corner">{{ tr('轨道') }}</div>
        <template v-for="track in tracks" :key="track.kind">
          <div v-for="lane in track.kind === 'audio' ? track.laneCount : 1" :key="lane" class="editor-track-name"
            :style="{ height: `${track.kind === 'audio' ? track.laneHeight + (lane === track.laneCount ? 8 : 0) : track.height}px` }">
            <component :is="track.icon" :size="14" />
            <strong>{{ track.kind === 'audio' && track.laneCount > 1 ? `BGM ${lane}` : kindLabel(track.kind) }}</strong>
            <button v-if="lane === 1" class="editor-icon-btn" :disabled="readOnly" :aria-label="tr('添加{p0}', { p0: kindLabel(track.kind) })" @click="emit('add', track.kind)"><Plus :size="13" /></button>
          </div>
        </template>
      </div>
      <div ref="canvas" class="editor-tracks-canvas" @pointerdown="startMarquee" :style="{ width: `${width}px` }"><div class="editor-time-ruler" @pointerdown="seek"><span v-for="mark in ticks" :key="mark" :style="{ left: `${mark * zoom}px` }">{{ format(mark) }}</span></div><div v-for="track in tracks" :key="track.kind" class="editor-track-row" :class="{ 'editor-audio-track': track.kind === 'audio' }" :style="{ height: `${track.height}px`, '--editor-lane-height': `${track.laneHeight}px`, backgroundSize: `${zoom * 5}px 100%` }"><span v-if="!track.items.length" class="editor-track-empty">{{ tr('从左侧添加素材') }}</span><button v-for="clip in track.items" :key="clip.id" v-memo="[clip, selectedSet.has(clip.id), clip.id === selectedId, selectedSet.size===1, previewClip(clip), zoom, track.positions.get(clip.id), readOnly, indexed]" class="editor-track-clip" :class="[`clip-${clip.type}`, { selected: selectedSet.has(clip.id), 'is-dragging': dragging?.id === clip.id, missing: 'source' in clip && indexed.get(sourceKey(clip.source))?.missing }]" :aria-pressed="selectedSet.has(clip.id)" :style="clipStyle(clip, track.positions.get(clip.id) || 0, track.laneHeight)" :aria-label="tr('选择{p0}：{p1}', { p0: kindLabel(clip.type), p1: clipTitle(clip) })" @pointerdown="drag($event, clip)" @dragstart.prevent @click="!$event.detail && chooseClip($event,clip)" @keydown.left.prevent="nudgeClip(clip, -1)" @keydown.right.prevent="nudgeClip(clip, 1)"><VideoThumbnail v-if="clip.type === 'video' && indexed.get(sourceKey(clip.source))?.url && !indexed.get(sourceKey(clip.source))?.missing" class="editor-timeline-thumbnail" :src="mediaUrl(indexed.get(sourceKey(clip.source))?.url)" :poster="poster(clip)" /><div v-else-if="poster(clip)" class="editor-filmstrip" :style="filmstripStyle(clip)"></div><component :is="track.icon" :size="12" /><span :title="clipTitle(clip)">{{ clipTitle(clip) }}</span><small>{{ previewClip(clip).duration.toFixed(1) }}s</small><i v-if="clip.id === selectedId && selectedSet.size===1 && !readOnly" class="editor-clip-handle left" role="separator" :aria-label="tr('调整片段入点')" tabindex="0" @pointerdown.stop="drag($event, clip, 'left')" @keydown.left.prevent.stop="emit('edge', clip.id, 'left', -1 / document.fps)" @keydown.right.prevent.stop="emit('edge', clip.id, 'left', 1 / document.fps)"></i><i v-if="clip.id === selectedId && selectedSet.size===1 && !readOnly" class="editor-clip-handle right" role="separator" :aria-label="tr('调整片段出点')" tabindex="0" @pointerdown.stop="drag($event, clip, 'right')" @keydown.left.prevent.stop="emit('edge', clip.id, 'right', -1 / document.fps)" @keydown.right.prevent.stop="emit('edge', clip.id, 'right', 1 / document.fps)"></i></button></div><div v-if="marquee" class="editor-selection-box" :style="{left:`${marquee.left}px`,top:`${marquee.top}px`,width:`${marquee.right-marquee.left}px`,height:`${marquee.bottom-marquee.top}px`}" aria-hidden="true"></div><div class="editor-playhead" @pointerdown.stop="seek" :style="{ transform: `translateX(${time * zoom}px)` }" aria-hidden="true"><i></i></div></div>
    </div><footer class="editor-timeline-footer"><span v-if="selectedSet.size>1">{{ tr('已选 {p0} 个片段 · 修改右侧属性可批量应用 · Delete/⌫ 移除',{p0:selectedSet.size}) }}</span><span v-else>{{ tr('拖动空白处框选 · Shift 连选 · ⌘/Ctrl 多选 · 空格播放 · Delete/⌫ 移除') }}</span></footer>
  </section>
</template>
