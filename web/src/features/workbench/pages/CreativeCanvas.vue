<script setup lang="ts">
import type { Edge, Node, NodeDragEvent, NodeTypesObject } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { SelectionMode, useVueFlow, VueFlow } from '@vue-flow/core'
import { MiniMap } from '@vue-flow/minimap'
import { computed, markRaw, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { notice } from '@/shared/notice'
import CanvasToolSwitcher from '../components/CanvasToolSwitcher.vue'
import WorkbenchToolbar from '../components/WorkbenchToolbar.vue'
import AssetReferenceEdge from '../edges/AssetReferenceEdge.vue'
import OutputBindingEdge from '../edges/OutputBindingEdge.vue'
import ShotSequenceEdge from '../edges/ShotSequenceEdge.vue'
import { buildWorkbenchAutoLayout } from '../layout/workbenchAutoLayout'
import AssetNode from '../nodes/AssetNode.vue'
import ChapterNode from '../nodes/ChapterNode.vue'
import ShotNode from '../nodes/ShotNode.vue'
import VideoResultNode from '../nodes/VideoResultNode.vue'
import { useWorkbenchStore } from '../store/workbenchStore'
import { loadWorkbenchViewport, saveWorkbenchViewport } from '../viewport/workbenchViewportPersistence'
import './noop.css'

const props = defineProps<{ novelId: number; chapterId: number }>()
const store = useWorkbenchStore()
const canvasTool = ref<'select' | 'pan'>('select')
const spacePanActive = ref(false)
const generating = ref(false)
const { fitView, getViewport, setViewport } = useVueFlow()
const nodeTypes: NodeTypesObject = { chapter: markRaw(ChapterNode), asset: markRaw(AssetNode), shot: markRaw(ShotNode), video_result: markRaw(VideoResultNode) }
const edgeTypes = { asset_reference: markRaw(AssetReferenceEdge), shot_sequence: markRaw(ShotSequenceEdge), output_binding: markRaw(OutputBindingEdge) }
const flowNodes = computed<Node[]>(() => store.nodes.map(item => ({ id: item.key, type: item.kind, position: item.position, zIndex: item.zIndex, selected: store.selectedNodeKeys.includes(item.key), data: { ...item.data, kind: item.kind, title: item.title, status: item.status } })))
const flowEdges = computed<Edge[]>(() => store.edges.map(item => ({ id: item.key, source: item.source, target: item.target, type: item.type, selected: store.selectedEdgeKeys.includes(item.key), sourceHandle: item.sourceHandle || undefined, targetHandle: item.targetHandle || undefined })))
const panModeActive = computed(() => canvasTool.value === 'pan' || spacePanActive.value)
const hasShotSelection = computed(() => store.selectedNodeKeys.some(key => store.nodeByKey(key)?.kind === 'shot'))
const canCopy = computed(() => store.selectedNodeKeys.length === 1 && store.nodeByKey(store.selectedNodeKeys[0])?.kind === 'shot')

function nodeDragStart() { store.checkpoint() }
function nodeDrag(event: NodeDragEvent) { store.updateNodeLayout(event.node.id, event.node.position) }
function nodeDragStop(event: NodeDragEvent) { store.updateNodeLayout(event.node.id, event.node.position); store.persistLayout() }
function selectNode(event: { event: MouseEvent | TouchEvent; node: Node }) { const source = event.event; store.selectNode(event.node.id, source instanceof MouseEvent && (source.metaKey || source.ctrlKey || source.shiftKey)) }
function canvasSize() { const canvas = document.getElementById('novel-workbench'); const bounds = canvas?.getBoundingClientRect(); return { width: Math.max(1, bounds?.width || window.innerWidth), height: Math.max(1, bounds?.height || window.innerHeight) } }
function moveEnd() { store.viewport = getViewport(); saveWorkbenchViewport(String(props.chapterId), store.viewport, canvasSize()); store.persistLayout() }
async function autoArrange() {
  store.checkpoint()
  const positions = buildWorkbenchAutoLayout(store.nodes, store.edges)
  store.nodes.forEach(item => { if (positions[item.key]) item.position = positions[item.key] })
  store.persistLayout(); await nextTick(); await fitView({ padding: 0.12, duration: 500 })
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
  if ((event.key === 'Delete' || event.key === 'Backspace') && hasShotSelection.value) { event.preventDefault(); store.deleteSelection() }
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
    <VueFlow v-else id="novel-workbench" class="viral-workbench-canvas" :class="{ 'is-pan-mode': panModeActive }" aria-label="小说视频创作画布" :nodes="flowNodes" :edges="flowEdges" :node-types="nodeTypes" :edge-types="edgeTypes" :default-viewport="store.viewport" :min-zoom="0.15" :max-zoom="2.5" :pan-on-drag="panModeActive" :nodes-draggable="!panModeActive" :elements-selectable="!panModeActive" :selection-key-code="!panModeActive" :selection-mode="SelectionMode.Partial" :delete-key-code="null" no-wheel-class-name="nowheel" pan-activation-key-code="Space" @node-drag-start="nodeDragStart" @node-drag="nodeDrag" @node-drag-stop="nodeDragStop" @node-click="selectNode" @pane-click="store.clearSelection" @move-end="moveEnd">
      <Background variant="lines" color="#2b2926" :gap="38" :line-width="1" />
      <MiniMap aria-hidden="true" :tabindex="-1" pannable zoomable />
      <Controls position="bottom-right" />
      <CanvasToolSwitcher v-model="canvasTool" />
      <WorkbenchToolbar :running="generating" :can-undo="store.canUndo" :can-redo="store.canRedo" :has-selection="hasShotSelection" :can-copy="canCopy" :can-paste="Boolean(store.clipboardNode)" @add-shot="store.addShot()" @generate="generateScenes" @delete-selection="store.deleteSelection" @copy="store.copySelection" @paste="store.paste" @undo="store.undo" @redo="store.redo" @auto-arrange="autoArrange" />
      <div v-if="store.nodes.length === 0" class="workbench-empty" role="status"><span>画布还是空的</span><button type="button" @click="store.addShot()">添加第一个镜头</button></div>
    </VueFlow>
  </main>
</template>
