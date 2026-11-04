<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Film, Music2, Type, Sticker, Plus, Scissors, Trash2, Undo2, Redo2, Copy, ZoomIn, ZoomOut } from 'lucide-vue-next'
import { mediaUrl } from '@/api'
import { tr } from '@/i18n'
import VideoThumbnail from '@/components/VideoThumbnail.vue'
import { clipTitle, kindLabel, sourceKey, totalDuration } from './model'
import type { ClipKind, EditClip, EditDocument, EditorMedia } from './types'
const props = defineProps<{ document: EditDocument; media: EditorMedia[]; time: number; selectedId: string; readOnly: boolean; canUndo: boolean; canRedo: boolean }>()
const emit = defineEmits<{ select: [id: string]; seek: [time: number]; move: [id: string, start: number]; edge: [id: string, side: 'left' | 'right', delta: number]; add: [kind: ClipKind]; split: []; remove: []; duplicate: []; undo: []; redo: [] }>()
const zoom = ref(24), viewport = ref<HTMLElement | null>(null), dragging = ref<{ id: string; start: number } | null>(null)
const indexed = computed(() => new Map(props.media.map(item => [item.key, item])))
const width = computed(() => Math.max(viewport.value?.clientWidth || 800, (totalDuration(props.document) + 5) * zoom.value))
const ticks = computed(() => Array.from({ length: Math.ceil(width.value / zoom.value / 5) + 1 }, (_, i) => i * 5))
const tracks = computed(() => (['sticker', 'subtitle', 'video', 'audio'] as ClipKind[]).map(kind => {
  const items = props.document.clips.filter(c => c.type === kind).sort((a, b) => a.start - b.start)
  const ends: number[] = [], positions = new Map<string, number>()
  for (const clip of items) { let lane = ends.findIndex(end => end <= clip.start + .001); if (lane < 0) lane = ends.length; ends[lane] = clip.start + clip.duration; positions.set(clip.id, lane) }
  const laneHeight = kind === 'video' ? 66 : kind === 'audio' ? 48 : 36
  return { kind, items, positions, laneHeight, height: Math.max(1, ends.length) * laneHeight + 8, icon: { video: Film, audio: Music2, subtitle: Type, sticker: Sticker }[kind] }
}))
let cleanup: (() => void) | null = null
function format(value: number) { return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(Math.floor(value % 60)).padStart(2, '0')}` }
function seek(event: PointerEvent) {
  const el = viewport.value
  if (!el || event.button !== 0) return
  event.preventDefault(); cleanup?.()
  const move = (current: PointerEvent) => {
    if (current.pointerId !== event.pointerId) return
    const time = (current.clientX - el.getBoundingClientRect().left + el.scrollLeft) / zoom.value
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
  cleanup?.(); const x = event.clientX, start = clip.start
  let delta = 0, moved = false
  const move = (current: PointerEvent) => { delta = (current.clientX - x) / zoom.value; if (Math.abs(current.clientX - x) > 3) moved = true; if (!edge) dragging.value = { id: clip.id, start: Math.max(0, start + delta) } }
  const stop = () => { cleanup?.(); if (moved) { if (edge) emit('edge', clip.id, edge, delta); else emit('move', clip.id, Math.max(0, start + delta)) } }
  cleanup = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stop); dragging.value = null; cleanup = null }
  window.addEventListener('pointermove', move); window.addEventListener('pointerup', stop, { once: true })
}
function clipStyle(clip: EditClip, lane: number, laneHeight: number) {
  return { left: `${(dragging.value?.id === clip.id ? dragging.value.start : clip.start) * zoom.value}px`, width: `${Math.max(12, clip.duration * zoom.value - 2)}px`, top: `${4 + lane * laneHeight}px`, height: `${laneHeight - 4}px` }
}
function poster(clip: EditClip) { return 'source' in clip ? mediaUrl(indexed.value.get(sourceKey(clip.source))?.poster || (clip.type === 'sticker' ? indexed.value.get(sourceKey(clip.source))?.url : '')) : '' }
function filmstripStyle(clip: EditClip) { return { backgroundImage: `url(${JSON.stringify(poster(clip))})` } }
function fit() { if (viewport.value) zoom.value = Math.min(300, Math.max(8, (viewport.value.clientWidth - 12) / Math.max(1, totalDuration(props.document)))) }
function reveal() {
  const el = viewport.value; if (!el) return
  const x = props.time * zoom.value
  if (x > el.scrollLeft + el.clientWidth - 40 || x < el.scrollLeft) el.scrollLeft = Math.max(0, x - el.clientWidth * .4)
}
onMounted(fit); onBeforeUnmount(() => cleanup?.())
defineExpose({ reveal })
</script>
<template>
  <section class="editor-timeline video-timeline" :aria-label="tr('多轨时间线')">
    <header class="editor-timeline-toolbar"><div class="editor-editing-tools"><button class="editor-icon-btn" :disabled="readOnly || !canUndo" :aria-label="tr('撤销')" @click="emit('undo')"><Undo2 :size="17" /></button><button class="editor-icon-btn" :disabled="readOnly || !canRedo" :aria-label="tr('重做')" @click="emit('redo')"><Redo2 :size="17" /></button><i></i><button class="editor-icon-btn" :disabled="readOnly || !selectedId" :aria-label="tr('在播放头处分割')" @click="emit('split')"><Scissors :size="17" /></button><button class="editor-icon-btn" :disabled="readOnly || !selectedId" :aria-label="tr('复制片段')" @click="emit('duplicate')"><Copy :size="16" /></button><button class="editor-icon-btn" :disabled="readOnly || !selectedId" :aria-label="tr('移除片段')" @click="emit('remove')"><Trash2 :size="16" /></button><span>{{ tr('本集时间线') }}</span></div><div class="editor-zoom"><button class="editor-icon-btn" :aria-label="tr('缩小时间线')" @click="zoom = Math.max(8, zoom - 4)"><ZoomOut :size="16" /></button><input v-model.number="zoom" type="range" min="8" max="300" :aria-label="tr('时间轴刻度尺寸')" /><button class="editor-icon-btn" :aria-label="tr('放大时间线')" @click="zoom = Math.min(300, zoom + 4)"><ZoomIn :size="16" /></button><button class="editor-link" @click="fit">{{ tr('适应') }}</button></div></header>
    <div class="editor-track-body"><div class="editor-track-labels"><div class="editor-ruler-corner">{{ tr('轨道') }}</div><div v-for="track in tracks" :key="track.kind" class="editor-track-name" :style="{ height: `${track.height}px` }"><component :is="track.icon" :size="14" /><strong>{{ kindLabel(track.kind) }}</strong><button class="editor-icon-btn" :disabled="readOnly" :aria-label="tr('添加{p0}', { p0: kindLabel(track.kind) })" @click="emit('add', track.kind)"><Plus :size="13" /></button></div></div>
      <div ref="viewport" class="editor-timeline-scroll"><div class="editor-tracks-canvas" :style="{ width: `${width}px` }"><div class="editor-time-ruler" @pointerdown="seek"><span v-for="mark in ticks" :key="mark" :style="{ left: `${mark * zoom}px` }">{{ format(mark) }}</span></div><div v-for="track in tracks" :key="track.kind" class="editor-track-row" :style="{ height: `${track.height}px`, backgroundSize: `${zoom * 5}px 100%` }"><span v-if="!track.items.length" class="editor-track-empty">{{ tr('从左侧添加素材') }}</span><button v-for="clip in track.items" :key="clip.id" class="editor-track-clip" :class="[`clip-${clip.type}`, { selected: clip.id === selectedId, missing: 'source' in clip && indexed.get(sourceKey(clip.source))?.missing }]" :style="clipStyle(clip, track.positions.get(clip.id) || 0, track.laneHeight)" :aria-label="tr('选择{p0}：{p1}', { p0: kindLabel(clip.type), p1: clipTitle(clip) })" @pointerdown="drag($event, clip)" @click="emit('select', clip.id)" @keydown.left.prevent="!readOnly && emit('move', clip.id, Math.max(0, clip.start - 1 / document.fps))" @keydown.right.prevent="!readOnly && emit('move', clip.id, clip.start + 1 / document.fps)"><VideoThumbnail v-if="clip.type === 'video' && indexed.get(sourceKey(clip.source))?.url && !indexed.get(sourceKey(clip.source))?.missing" class="editor-timeline-thumbnail" :src="mediaUrl(indexed.get(sourceKey(clip.source))?.url)" :poster="poster(clip)" /><div v-else-if="poster(clip)" class="editor-filmstrip" :style="filmstripStyle(clip)"></div><component :is="track.icon" :size="12" /><span :title="clipTitle(clip)">{{ clipTitle(clip) }}</span><small>{{ clip.duration.toFixed(1) }}s</small><i v-if="clip.id === selectedId && !readOnly" class="editor-clip-handle left" role="separator" :aria-label="tr('调整片段入点')" tabindex="0" @pointerdown.stop="drag($event, clip, 'left')" @keydown.left.prevent.stop="emit('edge', clip.id, 'left', -1 / document.fps)" @keydown.right.prevent.stop="emit('edge', clip.id, 'left', 1 / document.fps)"></i><i v-if="clip.id === selectedId && !readOnly" class="editor-clip-handle right" role="separator" :aria-label="tr('调整片段出点')" tabindex="0" @pointerdown.stop="drag($event, clip, 'right')" @keydown.left.prevent.stop="emit('edge', clip.id, 'right', -1 / document.fps)" @keydown.right.prevent.stop="emit('edge', clip.id, 'right', 1 / document.fps)"></i></button></div><div class="editor-playhead" @pointerdown.stop="seek" :style="{ transform: `translateX(${time * zoom}px)` }" aria-hidden="true"><i></i></div></div></div>
    </div><footer class="editor-timeline-footer">{{ tr('空格播放／暂停 · 方向键微移 · Delete 移除 · ⌘Z 撤销') }}</footer>
  </section>
</template>
