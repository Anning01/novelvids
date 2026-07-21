<script setup lang="ts">
import type { Connection, Edge, Node, NodeDragEvent, NodeTypesObject } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { PanOnScrollMode, SelectionMode, useVueFlow, VueFlow } from '@vue-flow/core'
import { MiniMap } from '@vue-flow/minimap'
import { computed, markRaw, nextTick, onBeforeUnmount, onMounted, provide, ref } from 'vue'
import { notice } from '@/shared/notice'
import CanvasToolSwitcher from '../components/CanvasToolSwitcher.vue'
import WorkbenchToolbar from '../components/WorkbenchToolbar.vue'
import AssetReferenceEdge from '../edges/AssetReferenceEdge.vue'
import OutputBindingEdge from '../edges/OutputBindingEdge.vue'
import ShotSequenceEdge from '../edges/ShotSequenceEdge.vue'
import { buildWorkbenchAutoLayout } from '../layout/workbenchAutoLayout'
import { canvasZoomModifier } from '../interaction/canvasZoomModifier'
import { workbenchSectionActionsKey } from '../interaction/sectionActions'
import AssetNode from '../nodes/AssetNode.vue'
import ChapterNode from '../nodes/ChapterNode.vue'
import ShotNode from '../nodes/ShotNode.vue'
import VideoResultNode from '../nodes/VideoResultNode.vue'
import AudioReferenceNode from '../nodes/AudioReferenceNode.vue'
import DigitalHumanNode from '../nodes/DigitalHumanNode.vue'
import NoteNode from '../nodes/NoteNode.vue'
import SectionNode from '../nodes/SectionNode.vue'
import type { Point, WorkbenchNode } from '../types/workbenchTypes'
import { useWorkbenchStore } from '../store/workbenchStore'
import { loadWorkbenchViewport, saveWorkbenchViewport } from '../viewport/workbenchViewportPersistence'
import './noop.css'

const props = defineProps<{ novelId: number; chapterId: number }>()
const store = useWorkbenchStore()
const canvasTool = ref<'select' | 'pan'>('select')
const spacePanActive = ref(false)
const generating = ref(false)
const sectionDropTargetKey = ref<string | null>(null)
const zoomActivationKeyCode = canvasZoomModifier()
const { fitView, getNodes, getViewport, setViewport } = useVueFlow()
const nodeTypes: NodeTypesObject = { chapter: markRaw(ChapterNode), asset: markRaw(AssetNode), audio_reference: markRaw(AudioReferenceNode), digital_human: markRaw(DigitalHumanNode), shot: markRaw(ShotNode), video_result: markRaw(VideoResultNode), section: markRaw(SectionNode), note: markRaw(NoteNode) }
const edgeTypes = { asset_reference: markRaw(AssetReferenceEdge), shot_sequence: markRaw(ShotSequenceEdge), output_binding: markRaw(OutputBindingEdge) }
const flowNodes = computed<Node[]>(() => store.nodes.map(item => ({
  id: item.key, type: item.kind, position: item.position, zIndex: item.zIndex, selected: store.selectedNodeKeys.includes(item.key),
  ...(item.size ? { dimensions: { ...item.size }, style: { width: `${item.size.width}px`, height: `${item.size.height}px` } } : {}),
  data: { ...item.data, kind: item.kind, title: item.title, status: item.status, ...(item.kind === 'section' ? { drop_candidate: sectionDropTargetKey.value === item.key } : {}) },
})))
const flowEdges = computed<Edge[]>(() => store.edges.map(item => ({ id: item.key, source: item.source, target: item.target, type: item.type, selected: store.selectedEdgeKeys.includes(item.key), sourceHandle: item.sourceHandle || undefined, targetHandle: item.targetHandle || undefined })))
const panModeActive = computed(() => canvasTool.value === 'pan' || spacePanActive.value)
const hasDeletableSelection = computed(() => store.selectedNodeKeys.some(key => ['shot', 'audio_reference', 'digital_human', 'section', 'note'].includes(store.nodeByKey(key)?.kind || '')))
const canCopy = computed(() => store.selectedNodeKeys.length === 1 && ['shot', 'note'].includes(store.nodeByKey(store.selectedNodeKeys[0])?.kind || ''))
const selectedSectionMembers = computed(() => store.selectedNodeKeys.map(key => store.nodeByKey(key)).filter((item): item is WorkbenchNode => Boolean(item && item.kind !== 'section')))
const canCreateSection = computed(() => selectedSectionMembers.value.length >= 2)

const SECTION_PADDING = 64
let sectionDrag: { sectionKey: string; startPosition: Point; memberPositions: Record<string, Point> } | null = null

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
  sectionDropTargetKey.value = null; store.persistLayout()
}
function selectNode(event: { event: MouseEvent | TouchEvent; node: Node }) { const source = event.event; store.selectNode(event.node.id, source instanceof MouseEvent && (source.metaKey || source.ctrlKey || source.shiftKey)) }
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
async function autoArrange() {
  store.checkpoint()
  const layoutNodes = store.nodes.filter(item => item.kind !== 'section' && item.kind !== 'note')
  const positions = buildWorkbenchAutoLayout(layoutNodes, store.edges)
  store.nodes.forEach(item => { if (positions[item.key]) item.position = positions[item.key] })
  store.persistLayout(); await nextTick(); await fitView({ padding: 0.12, duration: 500 })
}
function createSection(color: string) {
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
  store.addSection(memberKeys, geometry.position, geometry.size, color)
}
async function generateScenes() { generating.value = true; try { await store.generateScenes(); await nextTick(); await fitView({ padding: 0.12, duration: 500 }) } catch (error) { notice.error(error instanceof Error ? error.message : '分镜生成失败') } finally { generating.value = false } }
function handleKeydown(event: KeyboardEvent) {
  const target = event.target as HTMLElement | null
  if (target?.closest('input, textarea, select, [contenteditable="true"]')) return
  if (event.code === 'Space') { spacePanActive.value = true; event.preventDefault(); return }
  const command = event.metaKey || event.ctrlKey
  if (command && event.key.toLowerCase() === 'c') { event.preventDefault(); store.copySelection() }
  if (command && event.key.toLowerCase() === 'v') { event.preventDefault(); store.paste() }
  if (command && event.key.toLowerCase() === 'z') { event.preventDefault(); event.shiftKey ? store.redo() : store.undo() }
  if ((event.key === 'Delete' || event.key === 'Backspace') && hasDeletableSelection.value) { event.preventDefault(); store.deleteSelection() }
}
function handleKeyup(event: KeyboardEvent) { if (event.code === 'Space') spacePanActive.value = false }

onMounted(async () => {
  window.addEventListener('keydown', handleKeydown); window.addEventListener('keyup', handleKeyup)
  try { await store.load(props.novelId, props.chapterId); await nextTick(); const saved = loadWorkbenchViewport(String(props.chapterId), canvasSize()); if (saved) await setViewport(saved); else if (store.nodes.length) await fitView({ padding: 0.12 }) } catch (error) { notice.error(error instanceof Error ? error.message : '工作区加载失败') }
})
onBeforeUnmount(() => { window.removeEventListener('keydown', handleKeydown); window.removeEventListener('keyup', handleKeyup) })
</script>

<template>
  <main class="viral-workbench-page">
    <div v-if="store.loading" class="workbench-state" role="status">正在加载工作区…</div>
    <VueFlow v-else id="novel-workbench" class="viral-workbench-canvas" :class="{ 'is-pan-mode': panModeActive }" aria-label="小说视频创作画布" :nodes="flowNodes" :edges="flowEdges" :node-types="nodeTypes" :edge-types="edgeTypes" :default-viewport="store.viewport" :min-zoom="0.15" :max-zoom="2.5" :pan-on-drag="panModeActive" :pan-on-scroll="true" :pan-on-scroll-mode="PanOnScrollMode.Vertical" :zoom-on-scroll="false" :zoom-on-pinch="false" :zoom-activation-key-code="zoomActivationKeyCode" :nodes-draggable="!panModeActive" :elements-selectable="!panModeActive" :selection-key-code="!panModeActive" :selection-mode="SelectionMode.Partial" :delete-key-code="null" no-wheel-class-name="nowheel" pan-activation-key-code="Space" @node-drag-start="nodeDragStart" @node-drag="nodeDrag" @node-drag-stop="nodeDragStop" @node-click="selectNode" @pane-click="store.clearSelection" @move-end="moveEnd" @connect="connectNodes">
      <Background variant="lines" color="#2b2926" :gap="38" :line-width="1" />
      <MiniMap aria-hidden="true" :tabindex="-1" pannable zoomable />
      <Controls position="bottom-right" />
      <CanvasToolSwitcher v-model="canvasTool" />
      <WorkbenchToolbar :running="generating" :can-undo="store.canUndo" :can-redo="store.canRedo" :has-selection="hasDeletableSelection" :can-copy="canCopy" :can-paste="Boolean(store.clipboardNode)" :can-create-section="canCreateSection" @add-shot="store.addShot()" @add-audio="store.addMediaNode('audio_reference')" @add-digital-human="store.addMediaNode('digital_human')" @add-note="addNote" @create-section="createSection" @generate="generateScenes" @delete-selection="store.deleteSelection" @copy="store.copySelection" @paste="store.paste" @undo="store.undo" @redo="store.redo" @auto-arrange="autoArrange" />
      <div v-if="store.nodes.length === 0" class="workbench-empty" role="status"><span>画布还是空的</span><AppButton type="button" @click="store.addShot()">添加第一个镜头</AppButton></div>
    </VueFlow>
  </main>
</template>
