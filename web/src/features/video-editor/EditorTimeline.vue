<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Film, Music2, Type, Sticker, Plus, Scissors, Trash2, Undo2, Redo2, Copy, ZoomIn, ZoomOut } from 'lucide-vue-next'
import { mediaUrl } from '@/api'
import { tr } from '@/i18n'
import VideoThumbnail from '@/components/VideoThumbnail.vue'
import { clipTitle, frameTime, kindLabel, resizeClip, snapAudioStart, sourceKey, totalDuration } from './model'
import type { ClipKind, EditClip, EditDocument, EditorMedia } from './types'
const props = defineProps<{ document: EditDocument; media: EditorMedia[]; time: number; selectedId: string; readOnly: boolean; canUndo: boolean; canRedo: boolean }>()
const emit = defineEmits<{ select: [id: string]; seek: [time: number]; move: [id: string, start: number]; edge: [id: string, side: 'left' | 'right', delta: number]; add: [kind: ClipKind]; split: []; remove: []; duplicate: []; undo: []; redo: [] }>()
const AUDIO_SNAP_DISTANCE_PX = 8
const zoom = ref(24), viewport = ref<HTMLElement | null>(null), dragging = ref<EditClip | null>(null)
const canvas = ref<HTMLElement | null>(null), labels = ref<HTMLElement | null>(null)
function trackWidth() { return (viewport.value?.clientWidth ?? 0) - (labels.value?.offsetWidth ?? 0) }
const indexed = computed(() => new Map(props.media.map(item => [item.key, item])))
const width = computed(() => Math.max(trackWidth() || 800, (Math.max(totalDuration(props.document), dragging.value ? dragging.value.start + dragging.value.duration : 0) + 5) * zoom.value))
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
function drag(event: PointerEvent, clip: EditClip, edge?: 'left' | 'right') {
  emit('select', clip.id)
  if (props.readOnly || event.button !== 0) return
  event.preventDefault()
  if (event.currentTarget instanceof HTMLElement) event.currentTarget.focus({ preventScroll: true })
  cleanup?.(); const x = event.clientX, scroll = viewport.value?.scrollLeft || 0
  let delta = 0, moved = false
  const move = (current: PointerEvent) => {
    if (current.pointerId !== event.pointerId) return
    const distance = current.clientX - x + (viewport.value?.scrollLeft || 0) - scroll
    delta = distance / zoom.value
    if (Math.abs(distance) > 3) moved = true
    if (!moved) return
    if (edge) {
      const item = 'source' in clip ? indexed.value.get(sourceKey(clip.source)) : undefined
      try { dragging.value = resizeClip(props.document, clip.id, edge, delta, item).clips.find(item => item.id === clip.id)! }
      catch { /* Keep the last valid preview; the workspace reports invalid drops. */ }
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
      else if (moved && dragging.value) emit('move', clip.id, dragging.value.start)
    }
    cleanup?.()
  }
  cleanup = () => {
    window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stop)
    window.removeEventListener('pointercancel', stop); dragging.value = null; cleanup = null
  }
  window.addEventListener('pointermove', move); window.addEventListener('pointerup', stop)
  window.addEventListener('pointercancel', stop)
}
function previewClip(clip: EditClip) { return dragging.value?.id === clip.id ? dragging.value : clip }
function clipStyle(clip: EditClip, lane: number, laneHeight: number) {
  const preview = previewClip(clip)
  return { left: `${clip.start * zoom.value}px`, transform: dragging.value?.id === clip.id ? `translateX(${(preview.start - clip.start) * zoom.value}px)` : '', width: `${Math.max(12, preview.duration * zoom.value - 2)}px`, top: `${4 + lane * laneHeight}px`, height: `${laneHeight - 4}px` }
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
watch(() => [props.selectedId, props.document], () => {
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
    <header class="editor-timeline-toolbar"><div class="editor-editing-tools"><button class="editor-icon-btn" :disabled="readOnly || !canUndo" :aria-label="tr('撤销')" @click="emit('undo')"><Undo2 :size="17" /></button><button class="editor-icon-btn" :disabled="readOnly || !canRedo" :aria-label="tr('重做')" @click="emit('redo')"><Redo2 :size="17" /></button><i></i><button class="editor-icon-btn" :disabled="readOnly || !selectedId" :aria-label="tr('在播放头处分割')" @click="emit('split')"><Scissors :size="17" /></button><button class="editor-icon-btn" :disabled="readOnly || !selectedId" :aria-label="tr('复制片段')" :title="tr('复制片段（⌘D / Ctrl+D）')" aria-keyshortcuts="Meta+D Control+D" @click="emit('duplicate')"><Copy :size="16" /></button><button class="editor-icon-btn" :disabled="readOnly || !selectedId" :aria-label="tr('移除片段')" :title="tr('移除片段（Delete / ⌫）')" aria-keyshortcuts="Delete Backspace" @click="emit('remove')"><Trash2 :size="16" /></button><span>{{ tr('本集时间线') }}</span></div><div class="editor-zoom"><button class="editor-icon-btn" :aria-label="tr('缩小时间线')" @click="zoom = Math.max(8, zoom - 4)"><ZoomOut :size="16" /></button><input v-model.number="zoom" type="range" min="8" max="300" :aria-label="tr('时间轴刻度尺寸')" /><button class="editor-icon-btn" :aria-label="tr('放大时间线')" @click="zoom = Math.min(300, zoom + 4)"><ZoomIn :size="16" /></button><button class="editor-link" @click="fit">{{ tr('适应') }}</button></div></header>
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
      <div ref="canvas" class="editor-tracks-canvas" :style="{ width: `${width}px` }"><div class="editor-time-ruler" @pointerdown="seek"><span v-for="mark in ticks" :key="mark" :style="{ left: `${mark * zoom}px` }">{{ format(mark) }}</span></div><div v-for="track in tracks" :key="track.kind" class="editor-track-row" :class="{ 'editor-audio-track': track.kind === 'audio' }" :style="{ height: `${track.height}px`, '--editor-lane-height': `${track.laneHeight}px`, backgroundSize: `${zoom * 5}px 100%` }"><span v-if="!track.items.length" class="editor-track-empty">{{ tr('从左侧添加素材') }}</span><button v-for="clip in track.items" :key="clip.id" class="editor-track-clip" :class="[`clip-${clip.type}`, { selected: clip.id === selectedId, 'is-dragging': dragging?.id === clip.id, missing: 'source' in clip && indexed.get(sourceKey(clip.source))?.missing }]" :style="clipStyle(clip, track.positions.get(clip.id) || 0, track.laneHeight)" :aria-label="tr('选择{p0}：{p1}', { p0: kindLabel(clip.type), p1: clipTitle(clip) })" @pointerdown="drag($event, clip)" @dragstart.prevent @click="emit('select', clip.id)" @keydown.left.prevent="!readOnly && emit('move', clip.id, Math.max(0, clip.start - 1 / document.fps))" @keydown.right.prevent="!readOnly && emit('move', clip.id, clip.start + 1 / document.fps)"><VideoThumbnail v-if="clip.type === 'video' && indexed.get(sourceKey(clip.source))?.url && !indexed.get(sourceKey(clip.source))?.missing" class="editor-timeline-thumbnail" :src="mediaUrl(indexed.get(sourceKey(clip.source))?.url)" :poster="poster(clip)" /><div v-else-if="poster(clip)" class="editor-filmstrip" :style="filmstripStyle(clip)"></div><component :is="track.icon" :size="12" /><span :title="clipTitle(clip)">{{ clipTitle(clip) }}</span><small>{{ previewClip(clip).duration.toFixed(1) }}s</small><i v-if="clip.id === selectedId && !readOnly" class="editor-clip-handle left" role="separator" :aria-label="tr('调整片段入点')" tabindex="0" @pointerdown.stop="drag($event, clip, 'left')" @keydown.left.prevent.stop="emit('edge', clip.id, 'left', -1 / document.fps)" @keydown.right.prevent.stop="emit('edge', clip.id, 'left', 1 / document.fps)"></i><i v-if="clip.id === selectedId && !readOnly" class="editor-clip-handle right" role="separator" :aria-label="tr('调整片段出点')" tabindex="0" @pointerdown.stop="drag($event, clip, 'right')" @keydown.left.prevent.stop="emit('edge', clip.id, 'right', -1 / document.fps)" @keydown.right.prevent.stop="emit('edge', clip.id, 'right', 1 / document.fps)"></i></button></div><div class="editor-playhead" @pointerdown.stop="seek" :style="{ transform: `translateX(${time * zoom}px)` }" aria-hidden="true"><i></i></div></div>
    </div><footer class="editor-timeline-footer">{{ tr('空格播放／暂停 · Delete/⌫ 移除 · ⌘/Ctrl+C/V 复制粘贴 · ⌘/Ctrl+D 连续复制 · ⌘/Ctrl+Z 撤销') }}</footer>
  </section>
</template>
