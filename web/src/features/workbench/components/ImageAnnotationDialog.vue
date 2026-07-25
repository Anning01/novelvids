<script setup lang="ts">
import { ArrowUpRight, Check, Circle, Grid3X3, Hand, Minus, Pencil, Plus, RotateCcw, Square, Trash2, Undo2, X } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import {
  annotationReducer,
  emptyAnnotationState,
  normalizeImagePoint,
  type AnnotationEditorTool,
} from '../annotation/imageAnnotations'
import type { ImageAnnotation, ImageAnnotationTool, Point } from '../types/workbenchTypes'

const props = withDefaults(defineProps<{
  open: boolean
  imageUrl: string
  modelValue: ImageAnnotation[]
}>(), {
  imageUrl: '',
  modelValue: () => [],
})
const emit = defineEmits<{ close: []; save: [annotations: ImageAnnotation[]] }>()

const tools: Array<{ value: AnnotationEditorTool; label: string; icon: typeof Hand }> = [
  { value: 'move', label: '移动', icon: Hand },
  { value: 'rectangle', label: '矩形', icon: Square },
  { value: 'ellipse', label: '椭圆', icon: Circle },
  { value: 'grid', label: '网格', icon: Grid3X3 },
  { value: 'arrow', label: '箭头', icon: ArrowUpRight },
  { value: 'freehand', label: '涂鸦', icon: Pencil },
]
const state = ref(emptyAnnotationState())
const activeTool = ref<AnnotationEditorTool>('move')
const stroke = ref('#000000')
const strokeWidth = ref(1)
const zoom = ref(1)
const pan = ref<Point>({ x: 0, y: 0 })
const draft = ref<ImageAnnotation | null>(null)
const drawingPointerId = ref<number | null>(null)
const panStart = ref<{ client: Point; origin: Point } | null>(null)
const surface = ref<SVGSVGElement | null>(null)
const initialShapes = ref('[]')

const visibleShapes = computed(() => draft.value ? [...state.value.shapes, draft.value] : state.value.shapes)
const dirty = computed(() => JSON.stringify(state.value.shapes) !== initialShapes.value)
const transformStyle = computed(() => ({
  transform: `translate(${pan.value.x}px, ${pan.value.y}px) scale(${zoom.value})`,
}))

watch([() => props.open, () => props.modelValue], ([open]) => {
  if (!open) return
  state.value = annotationReducer(state.value, { type: 'load', shapes: props.modelValue })
  initialShapes.value = JSON.stringify(state.value.shapes)
  activeTool.value = 'move'
  draft.value = null
  resetView()
}, { immediate: true, deep: true })

function shapeId(tool: ImageAnnotationTool) {
  return `${tool}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}
function pointFromEvent(event: PointerEvent) {
  const bounds = surface.value?.getBoundingClientRect()
  return bounds ? normalizeImagePoint({ x: event.clientX, y: event.clientY }, bounds) : { x: 0, y: 0 }
}
function beginPointer(event: PointerEvent) {
  if (activeTool.value === 'move') {
    panStart.value = { client: { x: event.clientX, y: event.clientY }, origin: { ...pan.value } }
    ;(event.currentTarget as Element).setPointerCapture?.(event.pointerId)
    return
  }
  drawingPointerId.value = event.pointerId
  const point = pointFromEvent(event)
  draft.value = {
    id: shapeId(activeTool.value),
    tool: activeTool.value,
    points: activeTool.value === 'freehand' ? [point] : [point, point],
    stroke: stroke.value,
    strokeWidth: strokeWidth.value,
  }
  ;(event.currentTarget as Element).setPointerCapture?.(event.pointerId)
}
function movePointer(event: PointerEvent) {
  if (activeTool.value === 'move' && panStart.value) {
    pan.value = {
      x: panStart.value.origin.x + event.clientX - panStart.value.client.x,
      y: panStart.value.origin.y + event.clientY - panStart.value.client.y,
    }
    return
  }
  if (!draft.value || drawingPointerId.value !== event.pointerId) return
  const point = pointFromEvent(event)
  draft.value = draft.value.tool === 'freehand'
    ? { ...draft.value, points: [...draft.value.points, point] }
    : { ...draft.value, points: [draft.value.points[0]!, point] }
}
function endPointer(event: PointerEvent) {
  panStart.value = null
  if (!draft.value || drawingPointerId.value !== event.pointerId) return
  movePointer(event)
  const shape = draft.value
  draft.value = null
  drawingPointerId.value = null
  if (shape.points.length < 2) return
  state.value = annotationReducer(state.value, { type: 'add', shape })
}
function setTool(tool: AnnotationEditorTool) {
  activeTool.value = tool
  draft.value = null
  drawingPointerId.value = null
}
function adjustZoom(delta: number) {
  zoom.value = Math.min(4, Math.max(0.5, Number((zoom.value + delta).toFixed(2))))
}
function resetView() {
  zoom.value = 1
  pan.value = { x: 0, y: 0 }
}
function undo() {
  draft.value = null
  state.value = annotationReducer(state.value, { type: 'undo' })
}
function clear() {
  draft.value = null
  state.value = annotationReducer(state.value, { type: 'clear' })
}
function save() {
  if (!dirty.value) return
  emit('save', state.value.shapes.map(shape => ({ ...shape, points: shape.points.map(point => ({ ...point })) })))
}
function box(shape: ImageAnnotation) {
  const start = shape.points[0] || { x: 0, y: 0 }
  const end = shape.points.at(-1) || start
  return {
    x: Math.min(start.x, end.x),
    y: Math.min(start.y, end.y),
    width: Math.abs(end.x - start.x),
    height: Math.abs(end.y - start.y),
  }
}
function ellipse(shape: ImageAnnotation) {
  const bounds = box(shape)
  return { cx: bounds.x + bounds.width / 2, cy: bounds.y + bounds.height / 2, rx: bounds.width / 2, ry: bounds.height / 2 }
}
function points(shape: ImageAnnotation) {
  return shape.points.map(point => `${point.x},${point.y}`).join(' ')
}
function normalizedStrokeWidth(shape: ImageAnnotation) {
  return Math.max(0.0015, shape.strokeWidth / 700)
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="image-annotation-backdrop" role="presentation" @pointerdown.self="emit('close')">
      <section class="image-annotation-dialog" role="dialog" aria-modal="true" aria-label="图片标注编辑器">
        <header>
          <div><strong>图片标注</strong><small>拖动绘制，所有标注将随图片尺寸等比缩放</small></div>
          <button type="button" aria-label="关闭图片标注" @click="emit('close')"><X :size="18" aria-hidden="true" /></button>
        </header>

        <div class="image-annotation-dialog__toolbar">
          <div class="image-annotation-dialog__tools" role="toolbar" aria-label="批注工具">
            <button v-for="tool in tools" :key="tool.value" type="button" :class="{ 'is-active': activeTool === tool.value }" :aria-label="tool.label" :aria-pressed="activeTool === tool.value" @click="setTool(tool.value)">
              <component :is="tool.icon" :size="17" aria-hidden="true" /><span>{{ tool.label }}</span>
            </button>
          </div>
          <label class="image-annotation-dialog__stroke"><span>颜色</span><input v-model="stroke" type="color" aria-label="批注颜色"></label>
          <label class="image-annotation-dialog__brush"><span>画笔 {{ strokeWidth }}</span><input v-model.number="strokeWidth" type="range" min="1" max="12" step="1" aria-label="画笔粗细"></label>
          <div class="image-annotation-dialog__actions" role="group" aria-label="视图与历史操作">
            <button type="button" aria-label="缩小图片" @click="adjustZoom(-0.25)"><Minus :size="17" aria-hidden="true" /></button>
            <output aria-label="图片缩放比例">{{ Math.round(zoom * 100) }}%</output>
            <button type="button" aria-label="放大图片" @click="adjustZoom(0.25)"><Plus :size="17" aria-hidden="true" /></button>
            <button type="button" aria-label="重置图片视图" @click="resetView"><RotateCcw :size="17" aria-hidden="true" /></button>
            <button type="button" aria-label="撤销批注操作" :disabled="!state.history.length" @click="undo"><Undo2 :size="17" aria-hidden="true" /></button>
            <button type="button" aria-label="清空批注" :disabled="!state.shapes.length" @click="clear"><Trash2 :size="17" aria-hidden="true" /></button>
          </div>
        </div>

        <div class="image-annotation-dialog__viewport" :class="{ 'is-moving': activeTool === 'move' }">
          <div class="image-annotation-dialog__surface" :style="transformStyle">
            <img :src="imageUrl" alt="待标注图片">
            <svg ref="surface" viewBox="0 0 1 1" preserveAspectRatio="none" aria-label="图片批注画布" @pointerdown="beginPointer" @pointermove="movePointer" @pointerup="endPointer" @pointercancel="endPointer">
              <defs>
                <marker id="image-annotation-arrowhead" markerWidth="5" markerHeight="5" refX="4" refY="2.5" orient="auto" markerUnits="strokeWidth">
                  <path d="M0,0 L5,2.5 L0,5 z" fill="context-stroke" />
                </marker>
              </defs>
              <template v-for="shape in visibleShapes" :key="shape.id">
                <rect v-if="shape.tool === 'rectangle'" v-bind="box(shape)" fill="none" :stroke="shape.stroke" :stroke-width="normalizedStrokeWidth(shape)" />
                <ellipse v-else-if="shape.tool === 'ellipse'" v-bind="ellipse(shape)" fill="none" :stroke="shape.stroke" :stroke-width="normalizedStrokeWidth(shape)" />
                <g v-else-if="shape.tool === 'grid'" fill="none" :stroke="shape.stroke" :stroke-width="normalizedStrokeWidth(shape)">
                  <rect v-bind="box(shape)" />
                  <line :x1="box(shape).x + box(shape).width / 3" :y1="box(shape).y" :x2="box(shape).x + box(shape).width / 3" :y2="box(shape).y + box(shape).height" />
                  <line :x1="box(shape).x + box(shape).width * 2 / 3" :y1="box(shape).y" :x2="box(shape).x + box(shape).width * 2 / 3" :y2="box(shape).y + box(shape).height" />
                  <line :x1="box(shape).x" :y1="box(shape).y + box(shape).height / 3" :x2="box(shape).x + box(shape).width" :y2="box(shape).y + box(shape).height / 3" />
                  <line :x1="box(shape).x" :y1="box(shape).y + box(shape).height * 2 / 3" :x2="box(shape).x + box(shape).width" :y2="box(shape).y + box(shape).height * 2 / 3" />
                </g>
                <line v-else-if="shape.tool === 'arrow'" :x1="shape.points[0]?.x" :y1="shape.points[0]?.y" :x2="shape.points.at(-1)?.x" :y2="shape.points.at(-1)?.y" :stroke="shape.stroke" :stroke-width="normalizedStrokeWidth(shape)" marker-end="url(#image-annotation-arrowhead)" />
                <polyline v-else-if="shape.tool === 'freehand'" :points="points(shape)" fill="none" :stroke="shape.stroke" :stroke-width="normalizedStrokeWidth(shape)" stroke-linecap="round" stroke-linejoin="round" />
              </template>
            </svg>
          </div>
        </div>

        <footer>
          <span>{{ state.shapes.length }} 个标注</span>
          <div>
            <button type="button" aria-label="取消图片标注" @click="emit('close')">取消</button>
            <button type="button" class="is-primary" aria-label="保存图片标注" :disabled="!dirty" @click="save"><Check :size="16" aria-hidden="true" />保存</button>
          </div>
        </footer>
      </section>
    </div>
  </Teleport>
</template>
