<script setup lang="ts">
import type { Connection, Edge, Node, NodeChange, NodeDragEvent, NodeTypesObject } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { PanOnScrollMode, SelectionMode, VueFlow } from '@vue-flow/core'
import { MiniMap } from '@vue-flow/minimap'
import { Lock, Unlock } from 'lucide-vue-next'
import { computed, markRaw, nextTick, onBeforeUnmount, onMounted, provide, ref, watch } from 'vue'
import { notice } from '@/shared/notice'
import CanvasToolSwitcher from '../components/CanvasToolSwitcher.vue'
import WorkbenchToolbar from '../components/WorkbenchToolbar.vue'
import AssetReferenceEdge from '../edges/AssetReferenceEdge.vue'
import OutputBindingEdge from '../edges/OutputBindingEdge.vue'
import ShotSequenceEdge from '../edges/ShotSequenceEdge.vue'
import { buildWorkbenchGroupedAutoLayout } from '../layout/workbenchAutoLayout'
import { canvasZoomModifier } from '../interaction/canvasZoomModifier'
import { selectionAutoPanDelta, selectionRectAfterAutoPan } from '../interaction/selectionAutoPan'
import { workbenchSectionActionsKey } from '../interaction/sectionActions'
import { applyNodeSelectionChanges, isAdditiveSelectionEvent, sameSelection, selectionAfterNodeClick, selectionGestureMoved } from '../interaction/workbenchSelection'
import { workbenchPromptEditorKey } from '../prompt/promptEditor'
import { WORKBENCH_FLOW_ID, useWorkbenchFlow, workbenchInteractionState } from '../runtime/workbenchFlowRuntime'
import AssetNode from '../nodes/AssetNode.vue'
import ChapterNode from '../nodes/ChapterNode.vue'
import ShotNode from '../nodes/ShotNode.vue'
import VideoResultNode from '../nodes/VideoResultNode.vue'
import AudioReferenceNode from '../nodes/AudioReferenceNode.vue'
import DigitalHumanNode from '../nodes/DigitalHumanNode.vue'
import NoteNode from '../nodes/NoteNode.vue'
import SectionNode from '../nodes/SectionNode.vue'
import type { NodeSize, Point, WorkbenchNode } from '../types/workbenchTypes'
import { useWorkbenchStore } from '../store/workbenchStore'
import { loadWorkbenchViewport, saveWorkbenchViewport, WORKBENCH_MAX_ZOOM, WORKBENCH_MIN_ZOOM } from '../viewport/workbenchViewportPersistence'
import './noop.css'

const props = defineProps<{ novelId: number; chapterId: number }>()
const store = useWorkbenchStore()
const canvasTool = ref<'select' | 'pan'>('select')
const canvasLocked = ref(false)
const spacePanActive = ref(false)
const generating = ref(false)
const sectionDropTargetKey = ref<string | null>(null)
const promptEditorNodeKey = ref<string | null>(null)
const zoomActivationKeyCode = canvasZoomModifier()
const { fitView, getNodes, getViewport, panBy, setViewport, userSelectionRect, viewport, vueFlowRef } = useWorkbenchFlow()
const nodeTypes: NodeTypesObject = { chapter: markRaw(ChapterNode), asset: markRaw(AssetNode), audio_reference: markRaw(AudioReferenceNode), digital_human: markRaw(DigitalHumanNode), shot: markRaw(ShotNode), video_result: markRaw(VideoResultNode), section: markRaw(SectionNode), note: markRaw(NoteNode) }
const edgeTypes = { asset_reference: markRaw(AssetReferenceEdge), shot_sequence: markRaw(ShotSequenceEdge), output_binding: markRaw(OutputBindingEdge) }
const flowNodes = computed<Node[]>(() => store.nodes.map(item => ({
  id: item.key, type: item.kind, position: item.position, zIndex: item.zIndex, selected: store.selectedNodeKeys.includes(item.key),
  ...(item.size ? { dimensions: { ...item.size }, style: { width: `${item.size.width}px`, height: `${item.size.height}px` } } : {}),
  data: { ...item.data, kind: item.kind, title: item.title, status: item.status, ...(item.kind === 'section' ? { drop_candidate: sectionDropTargetKey.value === item.key } : {}) },
})))
const flowEdges = computed<Edge[]>(() => store.edges.map(item => ({ id: item.key, source: item.source, target: item.target, type: item.type, selected: store.selectedEdgeKeys.includes(item.key), sourceHandle: item.sourceHandle || undefined, targetHandle: item.targetHandle || undefined })))
const panModeActive = computed(() => canvasTool.value === 'pan' || spacePanActive.value)
const interactionState = computed(() => workbenchInteractionState(canvasLocked.value, panModeActive.value))
const hasDeletableSelection = computed(() => store.selectedNodeKeys.some(key => ['shot', 'audio_reference', 'digital_human', 'section', 'note'].includes(store.nodeByKey(key)?.kind || '')))
const canCopy = computed(() => store.selectedNodeKeys.length === 1 && ['shot', 'note'].includes(store.nodeByKey(store.selectedNodeKeys[0])?.kind || ''))
const selectedSectionMembers = computed(() => store.selectedNodeKeys.map(key => store.nodeByKey(key)).filter((item): item is WorkbenchNode => Boolean(item && item.kind !== 'section')))
const canCreateSection = computed(() => selectedSectionMembers.value.length >= 2)

provide(workbenchPromptEditorKey, {
  activeNodeKey: promptEditorNodeKey,
  open(nodeKey) {
    store.selectNode(nodeKey)
    promptEditorNodeKey.value = nodeKey
  },
  close(nodeKey) {
    if (!nodeKey || promptEditorNodeKey.value === nodeKey) promptEditorNodeKey.value = null
  },
})

const SECTION_PADDING = 64
const DEFAULT_SECTION_COLOR = '#31558f'
let sectionDrag: { sectionKey: string; startPosition: Point; memberPositions: Record<string, Point> } | null = null
let selectionIntent: {
  kind: 'node'
  key: string
  before: string[]
  additive: boolean
} | { kind: 'pane'; x: number; y: number } | null = null
let suppressNativeSelectionChanges = false
let selectionAutoPanFrame = 0
let selectionAutoPanPointer: { clientX: number; clientY: number } | null = null
let selectionAutoPanPane: HTMLElement | null = null
let selectionAutoPanMoved = false

function canvasNodeSize(item: WorkbenchNode) {
  const rendered = getNodes.value.find(candidate => candidate.id === item.key)?.dimensions
  if (rendered && rendered.width > 0 && rendered.height > 0) return { width: rendered.width, height: rendered.height }
  if (item.size) return item.size
  if (item.kind === 'shot') return { width: 360, height: 520 }
  if (item.kind === 'video_result') return { width: 360, height: 300 }
  if (item.kind === 'note') return { width: 320, height: 220 }
  return { width: 360, height: 280 }
}
function nodeGroupGeometry(items: WorkbenchNode[], padding = SECTION_PADDING) {
  const left = Math.min(...items.map(item => item.position.x)); const top = Math.min(...items.map(item => item.position.y))
  const right = Math.max(...items.map(item => item.position.x + canvasNodeSize(item).width)); const bottom = Math.max(...items.map(item => item.position.y + canvasNodeSize(item).height))
  return { position: { x: left - padding, y: top - padding }, size: { width: right - left + padding * 2, height: bottom - top + padding * 2 } }
}
function sectionMemberKeys(section: WorkbenchNode) { return Array.isArray(section.data.node_keys) ? section.data.node_keys.filter((key): key is string => typeof key === 'string') : [] }
function sectionMemberNodes(section: WorkbenchNode) { return sectionMemberKeys(section).map(key => store.nodeByKey(key)).filter((item): item is WorkbenchNode => Boolean(item && item.kind !== 'section')) }
function nodeCenter(item: WorkbenchNode, position = item.position) { const size = canvasNodeSize(item); return { x: position.x + size.width / 2, y: position.y + size.height / 2 } }
function sectionContainingPoint(point: Point, excludedKey?: string) {
  return store.nodes.filter(item => item.kind === 'section' && item.key !== excludedKey).filter((item) => {
    const size = item.size || { width: 420, height: 260 }
    return point.x >= item.position.x && point.x <= item.position.x + size.width && point.y >= item.position.y && point.y <= item.position.y + size.height
  }).sort((left, right) => {
    const leftSize = left.size || { width: 420, height: 260 }; const rightSize = right.size || { width: 420, height: 260 }
    return leftSize.width * leftSize.height - rightSize.width * rightSize.height || right.zIndex - left.zIndex
  })[0] || null
}
function reconcileMembership(nodeKeys: string[]) {
  const sections = store.nodes.filter(item => item.kind === 'section')
  const updates = new Map(sections.map(item => [item.key, new Set(sectionMemberKeys(item))]))
  nodeKeys.forEach((key) => {
    const item = store.nodeByKey(key); if (!item || item.kind === 'section') return
    const target = sectionContainingPoint(nodeCenter(item))
    updates.forEach((members, sectionKey) => sectionKey === target?.key ? members.add(key) : members.delete(key))
  })
  updates.forEach((members, key) => store.updateManualNodeData(key, { node_keys: [...members] }))
}
function absorbCoveredNodes(sectionKey: string) {
  const section = store.nodeByKey(sectionKey); if (!section || section.kind !== 'section') return
  const members = new Set(sectionMemberKeys(section))
  const assignedElsewhere = new Set(store.nodes.filter(item => item.kind === 'section' && item.key !== sectionKey).flatMap(sectionMemberKeys))
  store.nodes.forEach((item) => { if (item.kind !== 'section' && !assignedElsewhere.has(item.key) && sectionContainingPoint(nodeCenter(item))?.key === sectionKey) members.add(item.key) })
  store.updateManualNodeData(sectionKey, { node_keys: [...members] })
}
async function fitSectionToContent(sectionKey: string) {
  const section = store.nodeByKey(sectionKey); if (!section || section.kind !== 'section') return
  const members = sectionMemberNodes(section); if (!members.length) return
  store.checkpoint(); const geometry = nodeGroupGeometry(members); store.updateNodeLayout(sectionKey, geometry.position, geometry.size, section.zIndex); store.persistLayout()
}
provide(workbenchSectionActionsKey, { fitToContent: fitSectionToContent })

function nodeDragStart(event: NodeDragEvent) {
  if (selectionIntent?.kind === 'node' && selectionIntent.key === event.node.id) {
    applyAuthoritativeSelection(selectionAfterNodeClick(
      selectionIntent.before,
      selectionIntent.key,
      selectionIntent.additive,
    ))
  }
  store.checkpoint(); const item = store.nodeByKey(event.node.id)
  if (item?.kind === 'section') sectionDrag = { sectionKey: item.key, startPosition: { ...item.position }, memberPositions: Object.fromEntries(sectionMemberNodes(item).map(member => [member.key, { ...member.position }])) }
  else sectionDrag = null
}
function nodeDrag(event: NodeDragEvent) {
  if (sectionDrag && event.node.id === sectionDrag.sectionKey) {
    const delta = { x: event.node.position.x - sectionDrag.startPosition.x, y: event.node.position.y - sectionDrag.startPosition.y }
    store.updateNodeLayout(sectionDrag.sectionKey, event.node.position)
    Object.entries(sectionDrag.memberPositions).forEach(([key, position]) => store.updateNodeLayout(key, { x: position.x + delta.x, y: position.y + delta.y }))
    return
  }
  const draggedNodes = event.nodes?.length ? event.nodes : [event.node]
  draggedNodes.forEach(node => store.updateNodeLayout(node.id, node.position))
  const item = store.nodeByKey(event.node.id); sectionDropTargetKey.value = item && item.kind !== 'section' ? sectionContainingPoint(nodeCenter(item, event.node.position))?.key || null : null
}
function nodeDragStop(event: NodeDragEvent) {
  const draggedNodes = event.nodes?.length ? event.nodes : [event.node]
  draggedNodes.forEach(node => store.updateNodeLayout(node.id, node.position))
  if (sectionDrag?.sectionKey === event.node.id) { absorbCoveredNodes(event.node.id); sectionDrag = null }
  else reconcileMembership(draggedNodes.map(node => node.id))
  selectionIntent = null
  sectionDropTargetKey.value = null; store.persistLayout()
}
function handleNodesChange(changes: NodeChange[]) {
  if (selectionIntent || suppressNativeSelectionChanges) return
  const next = applyNodeSelectionChanges(
    store.selectedNodeKeys,
    changes,
    new Set(store.nodes.map(node => node.key)),
  )
  if (!sameSelection(next, store.selectedNodeKeys)) store.selectNodes(next)
}
function rememberSelectionIntent(event: PointerEvent) {
  if (event.button !== 0 || !(event.target instanceof Element)) {
    selectionIntent = null
    return
  }
  const nodeElement = event.target.closest<HTMLElement>('.vue-flow__node[data-id]')
  if (nodeElement?.dataset.id) {
    selectionIntent = {
      kind: 'node',
      key: nodeElement.dataset.id,
      before: [...store.selectedNodeKeys],
      additive: isAdditiveSelectionEvent(event),
    }
    return
  }
  selectionIntent = event.target.closest('.vue-flow__pane') && !event.target.closest('.vue-flow__edge')
    ? { kind: 'pane', x: event.clientX, y: event.clientY }
    : null
}
function applySelectionIntent() {
  const intent = selectionIntent
  selectionIntent = null
  if (!intent) return
  if (intent.kind === 'pane') {
    suppressNativeSelectionChanges = true
    store.clearSelection()
    void nextTick(() => { suppressNativeSelectionChanges = false })
    return
  }
  applyAuthoritativeSelection(selectionAfterNodeClick(intent.before, intent.key, intent.additive))
}
function applyAuthoritativeSelection(keys: string[]) {
  suppressNativeSelectionChanges = true
  store.selectNodes(keys)
  void nextTick(() => { suppressNativeSelectionChanges = false })
}
function connectNodes(connection: Connection) { if (connection.source && connection.target) store.connectMediaNode(connection.source, connection.target) }
function canvasSize() { const canvas = document.getElementById('novel-workbench'); const bounds = canvas?.getBoundingClientRect(); return { width: Math.max(1, bounds?.width || window.innerWidth), height: Math.max(1, bounds?.height || window.innerHeight) } }
function nextManualNodePosition(size: { width: number; height: number }) {
  const viewport = getViewport()
  const bounds = canvasSize()
  const zoom = Math.max(0.01, viewport.zoom)
  const visibleLeft = -viewport.x / zoom
  const visibleTop = -viewport.y / zoom
  return {
    x: Math.round(Math.max(visibleLeft + 24 / zoom, (bounds.width / 2 - viewport.x) / zoom - size.width / 2)),
    y: Math.round(Math.max(visibleTop + 64 / zoom, (bounds.height / 2 - viewport.y) / zoom - size.height / 2)),
  }
}
function addNote() { store.addNote(nextManualNodePosition({ width: 320, height: 220 })) }
function moveEnd() { store.viewport = getViewport(); saveWorkbenchViewport(String(props.chapterId), store.viewport, canvasSize()); store.persistLayout() }
function trackSelectionAutoPanPointer(event: PointerEvent) {
  selectionAutoPanPointer = { clientX: event.clientX, clientY: event.clientY }
  if (selectionIntent?.kind === 'pane' && selectionGestureMoved(
    { x: selectionIntent.x, y: selectionIntent.y },
    { x: event.clientX, y: event.clientY },
  )) selectionIntent = null
}
function refreshSelectionAtPointer() {
  if (!selectionAutoPanPane || !selectionAutoPanPointer) return
  selectionAutoPanPane.dispatchEvent(new PointerEvent('pointermove', {
    bubbles: true, buttons: 1, clientX: selectionAutoPanPointer.clientX, clientY: selectionAutoPanPointer.clientY, pointerType: 'mouse',
  }))
}
function runSelectionAutoPan() {
  const canvas = vueFlowRef.value
  const pointer = selectionAutoPanPointer
  if (!canvas || !pointer) return
  const bounds = canvas.getBoundingClientRect()
  const delta = selectionAutoPanDelta(
    { x: pointer.clientX - bounds.left, y: pointer.clientY - bounds.top },
    { width: bounds.width, height: bounds.height },
  )
  const previousViewport = getViewport()
  const panned = Boolean((delta.x || delta.y) && panBy(delta))
  if (panned) {
    const updatedViewport = getViewport()
    if (updatedViewport.x === previousViewport.x && updatedViewport.y === previousViewport.y) {
      viewport.value = { x: previousViewport.x + delta.x, y: previousViewport.y + delta.y, zoom: previousViewport.zoom }
    }
    if (userSelectionRect.value) {
      userSelectionRect.value = selectionRectAfterAutoPan(
        userSelectionRect.value,
        { x: pointer.clientX - bounds.left, y: pointer.clientY - bounds.top },
        delta,
      )
    }
    selectionAutoPanMoved = true
    refreshSelectionAtPointer()
  }
  selectionAutoPanFrame = window.requestAnimationFrame(runSelectionAutoPan)
}
function stopSelectionAutoPan() {
  window.cancelAnimationFrame(selectionAutoPanFrame)
  selectionAutoPanFrame = 0
  window.removeEventListener('pointermove', trackSelectionAutoPanPointer, true)
  window.removeEventListener('pointerup', stopSelectionAutoPan, true)
  window.removeEventListener('pointercancel', stopSelectionAutoPan, true)
  if (selectionAutoPanMoved) moveEnd()
  selectionAutoPanPointer = null
  selectionAutoPanPane = null
  selectionAutoPanMoved = false
}
function startSelectionAutoPan(event: MouseEvent) {
  stopSelectionAutoPan()
  selectionAutoPanPointer = { clientX: event.clientX, clientY: event.clientY }
  selectionAutoPanPane = event.target instanceof HTMLElement ? event.target : null
  window.addEventListener('pointermove', trackSelectionAutoPanPointer, true)
  window.addEventListener('pointerup', stopSelectionAutoPan, true)
  window.addEventListener('pointercancel', stopSelectionAutoPan, true)
  selectionAutoPanFrame = window.requestAnimationFrame(runSelectionAutoPan)
}
async function autoArrange() {
  store.checkpoint()
  const measuredSizes = Object.fromEntries(getNodes.value.flatMap((item) => {
    const { width, height } = item.dimensions
    return width > 0 && height > 0 ? [[item.id, { width, height } satisfies NodeSize]] : []
  }))
  const positions = buildWorkbenchGroupedAutoLayout(store.nodes, store.edges, { sizes: measuredSizes })
  store.nodes.forEach(item => { if (positions[item.key]) item.position = positions[item.key] })
  await nextTick()
  await fitView({ padding: 0.08, minZoom: WORKBENCH_MIN_ZOOM, maxZoom: 0.85, duration: 240 })
  store.viewport = getViewport()
  saveWorkbenchViewport(String(props.chapterId), store.viewport, canvasSize())
  store.persistLayout()
}
async function undoCanvasAction() {
  if (!store.undo()) return
  await nextTick()
  await setViewport(store.viewport)
  saveWorkbenchViewport(String(props.chapterId), store.viewport, canvasSize())
}
async function redoCanvasAction() {
  if (!store.redo()) return
  await nextTick()
  await setViewport(store.viewport)
  saveWorkbenchViewport(String(props.chapterId), store.viewport, canvasSize())
}
function createSection() {
  if (!canCreateSection.value) return
  store.checkpoint()
  const memberKeys = selectedSectionMembers.value.map(item => item.key)
  const memberSet = new Set(memberKeys)
  store.nodes.filter(node => node.kind === 'section').forEach((section) => {
    const remainingKeys = sectionMemberKeys(section).filter(key => !memberSet.has(key))
    if (remainingKeys.length !== sectionMemberKeys(section).length) {
      store.updateManualNodeData(section.key, { node_keys: remainingKeys })
    }
  })
  const geometry = nodeGroupGeometry(selectedSectionMembers.value)
  store.addSection(memberKeys, geometry.position, geometry.size, DEFAULT_SECTION_COLOR)
}
async function generateScenes() { generating.value = true; try { await store.generateScenes(); await nextTick(); await fitView({ padding: 0.12, duration: 500 }) } catch (error) { notice.error(error instanceof Error ? error.message : '分镜生成失败') } finally { generating.value = false } }
function handleKeydown(event: KeyboardEvent) {
  const target = event.target as HTMLElement | null
  if (target?.closest('input, textarea, select, [contenteditable="true"]')) return
  if (event.code === 'Space') { spacePanActive.value = true; event.preventDefault(); return }
  const command = event.metaKey || event.ctrlKey
  if (command && event.key.toLowerCase() === 'c') { event.preventDefault(); store.copySelection() }
  if (command && event.key.toLowerCase() === 'v') { event.preventDefault(); store.paste() }
  if (command && event.key.toLowerCase() === 'z') { event.preventDefault(); event.shiftKey ? void redoCanvasAction() : void undoCanvasAction() }
  if ((event.key === 'Delete' || event.key === 'Backspace') && hasDeletableSelection.value) { event.preventDefault(); store.deleteSelection() }
}
function handleKeyup(event: KeyboardEvent) { if (event.code === 'Space') spacePanActive.value = false }

watch([() => store.selectedNodeKeys[0], canvasTool], ([selectedNodeKey, tool]) => {
  if (tool === 'pan' || promptEditorNodeKey.value !== selectedNodeKey) promptEditorNodeKey.value = null
})

onMounted(async () => {
  window.addEventListener('keydown', handleKeydown); window.addEventListener('keyup', handleKeyup)
  try {
    await store.load(props.novelId, props.chapterId)
    await nextTick()
    const workspaceKey = String(props.chapterId)
    const saved = loadWorkbenchViewport(workspaceKey, canvasSize())
    if (saved) {
      await setViewport(saved)
    } else if (store.nodes.length) {
      await fitView({ padding: 0.12, minZoom: WORKBENCH_MIN_ZOOM, maxZoom: 0.85, duration: 0 })
    }
    store.viewport = getViewport()
    saveWorkbenchViewport(workspaceKey, store.viewport, canvasSize())
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '工作区加载失败')
  }
})
onBeforeUnmount(() => { stopSelectionAutoPan(); window.removeEventListener('keydown', handleKeydown); window.removeEventListener('keyup', handleKeyup) })
</script>

<template>
  <main class="viral-workbench-page" @pointerdown.capture="rememberSelectionIntent" @click.capture="applySelectionIntent">
    <div v-if="store.loading" class="workbench-state" role="status">正在加载工作区…</div>
    <VueFlow v-else :id="WORKBENCH_FLOW_ID" class="viral-workbench-canvas" :class="{ 'is-pan-mode': interactionState.panOnDrag, 'is-manual-pan-mode': canvasTool === 'pan', 'is-locked': canvasLocked }" aria-label="小说视频创作画布" :nodes="flowNodes" :edges="flowEdges" :node-types="nodeTypes" :edge-types="edgeTypes" :default-viewport="store.viewport" :min-zoom="WORKBENCH_MIN_ZOOM" :max-zoom="WORKBENCH_MAX_ZOOM" :pan-on-drag="interactionState.panOnDrag" :pan-on-scroll="true" :pan-on-scroll-mode="PanOnScrollMode.Vertical" :zoom-on-scroll="false" :zoom-on-pinch="false" :zoom-activation-key-code="zoomActivationKeyCode" :nodes-draggable="interactionState.nodesDraggable" :nodes-connectable="interactionState.nodesConnectable" :elements-selectable="interactionState.elementsSelectable" :select-nodes-on-drag="interactionState.selectNodesOnDrag" :selection-key-code="!interactionState.panOnDrag" :multi-selection-key-code="['Meta', 'Control', 'Shift']" :selection-mode="SelectionMode.Partial" :delete-key-code="null" no-wheel-class-name="nowheel" pan-activation-key-code="Space" @node-drag-start="nodeDragStart" @node-drag="nodeDrag" @node-drag-stop="nodeDragStop" @nodes-change="handleNodesChange" @pane-click="store.clearSelection" @selection-start="startSelectionAutoPan" @selection-end="stopSelectionAutoPan" @move-end="moveEnd" @connect="connectNodes">
      <Background variant="lines" color="#2b2926" :gap="38" :line-width="1" />
      <MiniMap aria-hidden="true" :tabindex="-1" pannable zoomable />
      <Controls position="bottom-right" :show-interactive="false">
        <button class="vue-flow__controls-button vue-flow__controls-interactive" type="button" :aria-pressed="canvasLocked" :aria-label="canvasLocked ? '解锁画布编辑' : '锁定画布编辑'" :title="canvasLocked ? '解锁画布编辑' : '锁定画布编辑'" @click.stop="canvasLocked = !canvasLocked">
          <Lock v-if="canvasLocked" :size="14" aria-hidden="true" />
          <Unlock v-else :size="14" aria-hidden="true" />
        </button>
      </Controls>
      <CanvasToolSwitcher v-model="canvasTool" />
      <WorkbenchToolbar :running="generating" :can-undo="store.canUndo" :can-redo="store.canRedo" :has-selection="hasDeletableSelection" :can-copy="canCopy" :can-paste="Boolean(store.clipboardNode)" :can-create-section="canCreateSection" @add-shot="store.addShot()" @add-audio="store.addMediaNode('audio_reference')" @add-digital-human="store.addMediaNode('digital_human')" @add-note="addNote" @create-section="createSection" @generate="generateScenes" @delete-selection="store.deleteSelection" @copy="store.copySelection" @paste="store.paste" @undo="undoCanvasAction" @redo="redoCanvasAction" @auto-arrange="autoArrange" />
      <div v-if="store.nodes.length === 0" class="workbench-empty" role="status"><span>画布还是空的</span><AppButton type="button" @click="store.addShot()">添加第一个镜头</AppButton></div>
    </VueFlow>
  </main>
</template>
