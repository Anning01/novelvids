<script setup lang="ts">
import { ArrowUpRight, Circle, Grid3X3, Move, Pencil, RotateCcw, Square, Trash2, Undo2, X, ZoomIn, ZoomOut } from 'lucide-vue-next'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { faceGridPolylines } from '@/shared/imageAnnotationGeometry'

type Tool = 'move' | 'rectangle' | 'ellipse' | 'face-grid' | 'arrow' | 'pen'
type DrawingTool = Exclude<Tool, 'move'>
interface Point { x: number; y: number }
interface Mark { tool: DrawingTool; color: string; brushSize: number; points: Point[] }
interface MarkDrag { index: number; pointerStart: Point; originalPoints: Point[] }

const props = withDefaults(defineProps<{ open: boolean; imageUrl: string; title?: string; saving?: boolean }>(), {
  title: '图片',
  saving: false,
})
const emit = defineEmits<{ close: []; save: [blob: Blob] }>()

const canvas = ref<HTMLCanvasElement | null>(null)
const root = ref<HTMLElement | null>(null)
const stage = ref<HTMLElement | null>(null)
const tool = ref<Tool>('rectangle')
const color = ref('#000000')
const brushSize = ref(1)
const zoom = ref(1)
const fittedSize = ref({ width: 0, height: 0 })
const marks = ref<Mark[]>([])
const drawing = ref<Mark | null>(null)
const markDrag = ref<MarkDrag | null>(null)
const loading = ref(false)
const error = ref('')
const sourceImage = new Image()
let resizeObserver: ResizeObserver | null = null

const canSave = computed(() => marks.value.length > 0 && !loading.value && !props.saving)
const canvasStyle = computed(() => fittedSize.value.width > 0 ? {
  width: `${fittedSize.value.width * zoom.value}px`,
  height: `${fittedSize.value.height * zoom.value}px`,
} : undefined)
const viewportStyle = computed(() => fittedSize.value.width > 0 ? {
  width: `max(100%, ${fittedSize.value.width * zoom.value}px)`,
  height: `max(100%, ${fittedSize.value.height * zoom.value}px)`,
} : undefined)
const zoomLabel = computed(() => `${Math.round(zoom.value * 100)}%`)

watch(() => [props.open, props.imageUrl] as const, async ([open, url]) => {
  if (!open || !url) return
  marks.value = []
  drawing.value = null
  markDrag.value = null
  zoom.value = 1
  fittedSize.value = { width: 0, height: 0 }
  error.value = ''
  loading.value = true
  await nextTick()
  root.value?.focus()
  sourceImage.onload = () => {
    const target = canvas.value
    if (!target) return
    target.width = sourceImage.naturalWidth
    target.height = sourceImage.naturalHeight
    loading.value = false
    render()
    void nextTick(updateFittedSize)
  }
  sourceImage.onerror = () => {
    loading.value = false
    error.value = '图片加载失败，请检查图片是否仍可访问'
  }
  sourceImage.crossOrigin = /^(data:|blob:)/.test(url) ? null : 'anonymous'
  sourceImage.src = url
}, { immediate: true })

watch(stage, target => {
  resizeObserver?.disconnect()
  resizeObserver = null
  if (target && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(updateFittedSize)
    resizeObserver.observe(target)
  }
}, { flush: 'post' })

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  sourceImage.onload = null
  sourceImage.onerror = null
})

function updateFittedSize() {
  const target = stage.value
  if (!target || !sourceImage.naturalWidth || !sourceImage.naturalHeight) return
  const scale = Math.min(1, (target.clientWidth - 28) / sourceImage.naturalWidth, (target.clientHeight - 28) / sourceImage.naturalHeight)
  fittedSize.value = { width: sourceImage.naturalWidth * scale, height: sourceImage.naturalHeight * scale }
}

function setZoom(value: number) {
  zoom.value = Math.min(3, Math.max(.5, Math.round(value * 4) / 4))
}

function point(event: PointerEvent): Point {
  const target = canvas.value!
  const box = target.getBoundingClientRect()
  return { x: (event.clientX - box.left) * target.width / box.width, y: (event.clientY - box.top) * target.height / box.height }
}

function start(event: PointerEvent) {
  if (loading.value || !canvas.value) return
  const origin = point(event)
  if (tool.value === 'move') {
    const index = findMarkAt(origin)
    if (index < 0) return
    canvas.value.setPointerCapture(event.pointerId)
    markDrag.value = { index, pointerStart: origin, originalPoints: marks.value[index]!.points.map(item => ({ ...item })) }
    return
  }
  canvas.value.setPointerCapture(event.pointerId)
  drawing.value = { tool: tool.value, color: color.value, brushSize: brushSize.value, points: [origin, origin] }
  render()
}

function move(event: PointerEvent) {
  if (markDrag.value && canvas.value) {
    const drag = markDrag.value
    const mark = marks.value[drag.index]
    if (!mark) return
    const next = point(event)
    const bounds = pointsBounds(drag.originalPoints)
    const deltaX = Math.min(canvas.value.width - bounds.maxX, Math.max(-bounds.minX, next.x - drag.pointerStart.x))
    const deltaY = Math.min(canvas.value.height - bounds.maxY, Math.max(-bounds.minY, next.y - drag.pointerStart.y))
    marks.value[drag.index] = { ...mark, points: drag.originalPoints.map(item => ({ x: item.x + deltaX, y: item.y + deltaY })) }
    render()
    return
  }
  if (!drawing.value) return
  const next = point(event)
  if (drawing.value.tool === 'pen') drawing.value.points.push(next)
  else drawing.value.points[1] = ['ellipse', 'face-grid'].includes(drawing.value.tool) && event.shiftKey
    ? constrainToCircle(drawing.value.points[0]!, next)
    : next
  render()
}

function finish(event: PointerEvent) {
  if (markDrag.value) {
    canvas.value?.releasePointerCapture(event.pointerId)
    markDrag.value = null
    render()
    return
  }
  if (!drawing.value) return
  canvas.value?.releasePointerCapture(event.pointerId)
  const mark = drawing.value
  drawing.value = null
  const first = mark.points[0]
  const last = mark.points.at(-1)
  if (first && last && Math.hypot(last.x - first.x, last.y - first.y) > 3) marks.value = [...marks.value, mark]
  render()
}

function constrainToCircle(origin: Point, next: Point): Point {
  const dx = next.x - origin.x
  const dy = next.y - origin.y
  const diameter = Math.max(Math.abs(dx), Math.abs(dy))
  return { x: origin.x + (dx < 0 ? -diameter : diameter), y: origin.y + (dy < 0 ? -diameter : diameter) }
}

function pointsBounds(points: Point[]) {
  const xs = points.map(item => item.x)
  const ys = points.map(item => item.y)
  return { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) }
}

function findMarkAt(position: Point) {
  const tolerance = Math.max(12, (canvas.value?.width ?? 0) / 100)
  for (let index = marks.value.length - 1; index >= 0; index -= 1) {
    const bounds = pointsBounds(marks.value[index]!.points)
    if (position.x >= bounds.minX - tolerance && position.x <= bounds.maxX + tolerance && position.y >= bounds.minY - tolerance && position.y <= bounds.maxY + tolerance) return index
  }
  return -1
}

function render() {
  const target = canvas.value
  const context = target?.getContext('2d')
  if (!target || !context || !sourceImage.complete) return
  context.clearRect(0, 0, target.width, target.height)
  context.drawImage(sourceImage, 0, 0, target.width, target.height)
  for (const mark of [...marks.value, ...(drawing.value ? [drawing.value] : [])]) drawMark(context, mark, target.width)
}

function drawMark(context: CanvasRenderingContext2D, mark: Mark, width: number) {
  const first = mark.points[0]
  const last = mark.points.at(-1)
  if (!first || !last) return
  const lineWidth = Math.max(.75, width / 1400) * mark.brushSize
  context.save()
  context.strokeStyle = mark.color
  context.fillStyle = mark.color
  context.lineWidth = lineWidth
  context.lineCap = 'round'
  context.lineJoin = 'round'
  context.beginPath()
  if (mark.tool === 'rectangle') context.strokeRect(first.x, first.y, last.x - first.x, last.y - first.y)
  else if (mark.tool === 'face-grid') {
    for (const line of faceGridPolylines(first, last)) {
      if (!line[0]) continue
      context.beginPath(); context.moveTo(line[0].x, line[0].y)
      for (const item of line.slice(1)) context.lineTo(item.x, item.y)
      context.stroke()
    }
  } else if (mark.tool === 'ellipse') {
    context.ellipse((first.x + last.x) / 2, (first.y + last.y) / 2, Math.max(lineWidth / 2, Math.abs(last.x - first.x) / 2), Math.max(lineWidth / 2, Math.abs(last.y - first.y) / 2), 0, 0, Math.PI * 2)
    context.stroke()
  } else if (mark.tool === 'pen') {
    context.moveTo(first.x, first.y)
    for (const item of mark.points.slice(1)) context.lineTo(item.x, item.y)
    context.stroke()
  } else {
    context.moveTo(first.x, first.y); context.lineTo(last.x, last.y); context.stroke()
    const angle = Math.atan2(last.y - first.y, last.x - first.x)
    const head = Math.max(16, width / 45, lineWidth * 4)
    context.beginPath(); context.moveTo(last.x, last.y)
    context.lineTo(last.x - head * Math.cos(angle - Math.PI / 6), last.y - head * Math.sin(angle - Math.PI / 6))
    context.lineTo(last.x - head * Math.cos(angle + Math.PI / 6), last.y - head * Math.sin(angle + Math.PI / 6))
    context.closePath(); context.fill()
  }
  context.restore()
}

function undo() { markDrag.value = null; marks.value = marks.value.slice(0, -1); render() }
function clear() { markDrag.value = null; marks.value = []; render() }
function save() {
  if (!canSave.value) return
  canvas.value?.toBlob(blob => {
    if (!blob) error.value = '标注图导出失败'
    else if (blob.size > 30 * 1024 * 1024) error.value = '标注图超过 30MB，请减少涂鸦或使用较小原图'
    else emit('save', blob)
  }, 'image/png')
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" ref="root" class="image-annotation" role="dialog" aria-modal="true" :aria-label="`${title}图片标注`" tabindex="-1" @keydown.esc.stop="emit('close')">
      <div class="image-annotation__panel">
        <header><strong>{{ title }} · 图片标注</strong><button type="button" aria-label="关闭图片标注" @click="emit('close')"><X :size="18" /></button></header>
        <div class="image-annotation__toolbar" role="toolbar" aria-label="图片标注工具">
          <button type="button" :class="{ 'is-active': tool === 'move' }" title="拖动已绘制标注" @click="tool = 'move'"><Move :size="17" />移动</button>
          <button type="button" :class="{ 'is-active': tool === 'rectangle' }" @click="tool = 'rectangle'"><Square :size="17" />矩形</button>
          <button type="button" :class="{ 'is-active': tool === 'ellipse' }" title="按住 Shift 绘制正圆" @click="tool = 'ellipse'"><Circle :size="17" />椭圆</button>
          <button type="button" :class="{ 'is-active': tool === 'face-grid' }" title="拖出椭圆范围生成人脸网格" @click="tool = 'face-grid'"><Grid3X3 :size="17" />网格</button>
          <button type="button" :class="{ 'is-active': tool === 'arrow' }" @click="tool = 'arrow'"><ArrowUpRight :size="17" />箭头</button>
          <button type="button" :class="{ 'is-active': tool === 'pen' }" @click="tool = 'pen'"><Pencil :size="17" />涂鸦</button>
          <label><span>粗细</span><input v-model.number="brushSize" type="range" min="0.5" max="6" step="0.5" aria-label="画笔粗细"><output>{{ brushSize }}</output></label>
          <label class="image-annotation__color"><span>颜色</span><input v-model="color" type="color" aria-label="标注颜色"></label>
          <span class="image-annotation__zoom"><button type="button" :disabled="zoom <= .5" aria-label="缩小" @click="setZoom(zoom - .25)"><ZoomOut :size="17" /></button><output>{{ zoomLabel }}</output><button type="button" :disabled="zoom >= 3" aria-label="放大" @click="setZoom(zoom + .25)"><ZoomIn :size="17" /></button><button type="button" :disabled="zoom === 1" aria-label="重置缩放" @click="setZoom(1)"><RotateCcw :size="16" /></button></span>
          <button type="button" :disabled="!marks.length" @click="undo"><Undo2 :size="17" />撤销</button>
          <button type="button" :disabled="!marks.length" @click="clear"><Trash2 :size="17" />清空</button>
        </div>
        <div ref="stage" class="image-annotation__stage">
          <div class="image-annotation__viewport" :style="viewportStyle"><canvas ref="canvas" :style="canvasStyle" :class="{ 'is-move': tool === 'move' }" @pointerdown="start" @pointermove="move" @pointerup="finish" @pointercancel="finish" /></div>
          <span v-if="loading">图片加载中…</span>
        </div>
        <p v-if="error" role="alert">{{ error }}</p>
        <footer><small>保存后会生成一条新的图片记录，原图仍保留在历史记录中。</small><button type="button" :disabled="!canSave" @click="save">{{ saving ? '保存中…' : '保存标注图' }}</button></footer>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.image-annotation{position:fixed;inset:0;z-index:2200;display:grid;padding:24px;place-items:center;background:rgb(12 12 14 / 72%);backdrop-filter:blur(8px)}
.image-annotation__panel{display:grid;width:min(1760px,96vw);height:min(94vh,1180px);grid-template-rows:auto auto minmax(0,1fr) auto auto;overflow:hidden;border:1px solid var(--app-border-strong);border-radius:18px;color:var(--app-text);background:var(--app-surface);box-shadow:0 32px 90px rgb(0 0 0 / 36%)}
.image-annotation__panel>header,.image-annotation__panel>footer{display:flex;align-items:center;justify-content:space-between;padding:16px 20px}.image-annotation__panel>header{border-bottom:1px solid var(--app-border);font-size:16px}.image-annotation button{display:inline-flex;align-items:center;justify-content:center;gap:7px;min-height:34px;padding:0 10px;border:1px solid var(--app-border-strong);border-radius:9px;color:var(--app-text-secondary);background:var(--app-surface-muted);cursor:pointer}.image-annotation button:hover:not(:disabled),.image-annotation button.is-active{border-color:var(--app-accent);color:var(--app-accent);background:var(--app-accent-soft)}.image-annotation button:disabled{opacity:.38;cursor:not-allowed}
.image-annotation__toolbar{display:flex;align-items:center;gap:7px;overflow-x:auto;padding:10px 16px;border-bottom:1px solid var(--app-border);color:var(--app-text-secondary);background:var(--app-surface-raised);scrollbar-width:none}.image-annotation__toolbar::-webkit-scrollbar{display:none}.image-annotation__toolbar label{display:flex;align-items:center;gap:8px;min-height:34px;padding:0 10px;border:1px solid var(--app-border-strong);border-radius:9px;background:var(--app-surface-muted);white-space:nowrap}.image-annotation__toolbar input[type=range]{width:100px;accent-color:var(--app-accent)}.image-annotation__color input{width:34px;height:25px;padding:0;border:0;background:none}.image-annotation__zoom{display:flex;align-items:center;border:1px solid var(--app-border-strong);border-radius:9px;background:var(--app-surface-muted)}.image-annotation__zoom button{border:0;background:transparent}.image-annotation__zoom output{min-width:52px;text-align:center}.image-annotation__undo{transform:scaleX(-1)}
.image-annotation__stage{position:relative;min-height:320px;overflow:auto;padding:14px;background:var(--app-canvas);scrollbar-width:none}.image-annotation__stage::-webkit-scrollbar{display:none}.image-annotation__viewport{display:grid;place-items:center}.image-annotation canvas{display:block;max-width:none;touch-action:none;cursor:crosshair}.image-annotation canvas.is-move{cursor:move}.image-annotation__stage>span{position:absolute;inset:0;display:grid;place-items:center;color:var(--app-text-secondary);background:color-mix(in srgb,var(--app-surface-raised) 82%,transparent)}
.image-annotation__panel>p{margin:0;padding:8px 20px;color:#c45461;background:color-mix(in srgb,#df596c 12%,var(--app-surface));font-size:12px}.image-annotation__panel>footer{border-top:1px solid var(--app-border);color:var(--app-text-muted);background:var(--app-surface-raised)}.image-annotation__panel>footer button{border-color:#7e63dc;color:#fff;background:#6650c5}.image-annotation__panel>footer button:hover:not(:disabled){border-color:#7055d3;color:#fff;background:#5943b8}.image-annotation__panel>footer small{font-size:11px}
@media(max-width:900px){.image-annotation{padding:8px}.image-annotation__panel{width:100%;height:98vh}.image-annotation__toolbar button{font-size:0}.image-annotation__toolbar button svg{margin:0}}
</style>
