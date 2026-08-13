<script setup lang="ts">
import type { Connection, Edge, Node, NodeChange, NodeDragEvent, NodeTypesObject, OnConnectStartParams } from '@vue-flow/core'
import type { CompatibleNodeCreation, WorkbenchConnectionOrigin, WorkbenchNodeCreationCandidate } from '../graph/nodeCreationRules'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { PanOnScrollMode, SelectionMode, VueFlow } from '@vue-flow/core'
import { MiniMap } from '@vue-flow/minimap'
import { computed, markRaw, nextTick, onBeforeUnmount, onMounted, provide, ref, watch } from 'vue'
import { api } from '@/api'
import { notice } from '@/shared/notice'
import type { WorkbenchCapabilities } from '@/types'
import CanvasToolSwitcher from '../components/CanvasToolSwitcher.vue'
import ConnectionNodePicker from '../components/ConnectionNodePicker.vue'
import ProjectAssetPicker from '../components/ProjectAssetPicker.vue'
import WorkbenchRunStatus from '../components/WorkbenchRunStatus.vue'
import WorkbenchToolbar from '../components/WorkbenchToolbar.vue'
import AssetReferenceEdge from '../edges/AssetReferenceEdge.vue'
import OutputBindingEdge from '../edges/OutputBindingEdge.vue'
import ShotSequenceEdge from '../edges/ShotSequenceEdge.vue'
import { buildWorkbenchGroupedAutoLayout } from '../layout/workbenchAutoLayout'
import { canvasZoomModifier } from '../interaction/canvasZoomModifier'
import { selectionAutoPanDelta, selectionRectAfterAutoPan } from '../interaction/selectionAutoPan'
import { workbenchSectionActionsKey } from '../interaction/sectionActions'
import { applyNodeSelectionChanges, isAdditiveSelectionEvent, isInteractiveSelectionTarget, sameSelection, selectionAfterNodeClick, selectionGestureMoved } from '../interaction/workbenchSelection'
import { selectedRunState } from '../execution/workbenchCapabilities'
import { normalizeShotConfig, SHOT_ASPECT_RATIOS, SHOT_RESOLUTIONS, shotGenerationOptions, type ShotAspectRatio, type ShotResolution } from '../config/shotConfig'
import { nodeCapabilities } from '../config/nodeCapabilities'
import { nodeExposesHandle, workbenchNodeHandles } from '../graph/handleCapabilities'
import { compatibleNodeCreations } from '../graph/nodeCreationRules'
import { createWorkbenchPromptActionRegistry, workbenchPromptActionRegistryKey } from '../prompt/promptActionRegistry'
import { promptEditorForNode, workbenchPromptEditorKey } from '../prompt/promptEditor'
import { createWorkbenchNodeRunRegistry, workbenchNodeRunRegistryKey } from '../run/nodeRunRegistry'
import type { KeyboardHandleActivation } from '../keyboard/keyboardConnection'
import { workbenchKeyboardConnectorKey } from '../keyboard/keyboardConnection'
import { isWorkbenchFlowReady, WORKBENCH_FLOW_ID, useWorkbenchFlow, workbenchInteractionState } from '../runtime/workbenchFlowRuntime'
import AssetNode from '../nodes/AssetNode.vue'
import ChapterNode from '../nodes/ChapterNode.vue'
import ShotNode from '../nodes/ShotNode.vue'
import VideoResultNode from '../nodes/VideoResultNode.vue'
import AudioReferenceNode from '../nodes/AudioReferenceNode.vue'
import DigitalHumanNode from '../nodes/DigitalHumanNode.vue'
import ImageMediaNode from '../nodes/ImageMediaNode.vue'
import VideoMediaNode from '../nodes/VideoMediaNode.vue'
import AudioMediaNode from '../nodes/AudioMediaNode.vue'
import WatermarkNode from '../nodes/WatermarkNode.vue'
import VideoComposerNode from '../nodes/VideoComposerNode.vue'
import NoteNode from '../nodes/NoteNode.vue'
import SectionNode from '../nodes/SectionNode.vue'
import type { NodeSize, Point, WorkbenchEdge, WorkbenchNode, WorkbenchNodeKind, WorkbenchPromptEditor } from '../types/workbenchTypes'
import { useWorkbenchStore } from '../store/workbenchStore'
import { screenPointForCenteredNode } from '../viewport/workbenchCoordinates'
import { loadWorkbenchViewport, saveWorkbenchViewport, WORKBENCH_MAX_ZOOM, WORKBENCH_MIN_ZOOM } from '../viewport/workbenchViewportPersistence'
import './noop.css'

const props = withDefaults(defineProps<{ novelId: number; chapterId: number; aspectRatio?: string; resolution?: string }>(), {
  aspectRatio: '9:16',
  resolution: '720p',
})
const store = useWorkbenchStore()
const canvasTool = ref<'select' | 'pan'>('select')
const spacePanActive = ref(false)
const generating = ref(false)
const capabilities = ref<WorkbenchCapabilities>({
  upload_media: false,
  generate_asset: false,
  generate_video: false,
  apply_watermark: false,
  compose_video: false,
  prompt_editors: [],
  refresh_policy: {
    poll_interval_ms: 1500,
    poll_max_interval_ms: 12000,
  },
})
const sectionDropTargetKey = ref<string | null>(null)
const promptEditorNodeKey = ref<string | null>(null)
const keyboardStatus = ref('尚未选择连线起点')
const projectAssetPickerOpen = ref(false)
const promptActionRegistry = createWorkbenchPromptActionRegistry()
provide(workbenchPromptActionRegistryKey, promptActionRegistry)
const nodeRunRegistry = createWorkbenchNodeRunRegistry()
provide(workbenchNodeRunRegistryKey, nodeRunRegistry)
const promptEditors = computed<WorkbenchPromptEditor[]>(() => (capabilities.value.prompt_editors ?? []).map(editor => ({
  editorKey: editor.editor_key,
  nodeKind: editor.node_kind,
  fieldKey: editor.field_key,
  label: editor.label,
  placeholder: editor.placeholder,
  hint: editor.hint,
  allowedAssetTypes: editor.allowed_asset_types,
  excludedAssetTypes: editor.excluded_asset_types,
  referenceLimits: { ...editor.reference_limits },
  allowPromptInjection: editor.allow_prompt_injection,
})))
const restoredViewportChapterId = ref<number | null>(null)
const zoomActivationKeyCode = canvasZoomModifier()
const { fitView, getNodes, getViewport, panBy, screenToFlowCoordinate, setViewport, userSelectionRect, viewport, vueFlowRef } = useWorkbenchFlow()
const nodeTypes: NodeTypesObject = { chapter: markRaw(ChapterNode), asset: markRaw(AssetNode), audio_reference: markRaw(AudioReferenceNode), digital_human: markRaw(DigitalHumanNode), image_media: markRaw(ImageMediaNode), video_media: markRaw(VideoMediaNode), audio_media: markRaw(AudioMediaNode), shot: markRaw(ShotNode), video_result: markRaw(VideoResultNode), watermark: markRaw(WatermarkNode), video_composer: markRaw(VideoComposerNode), section: markRaw(SectionNode), note: markRaw(NoteNode) }
const edgeTypes = { asset_reference: markRaw(AssetReferenceEdge), shot_sequence: markRaw(ShotSequenceEdge), output_binding: markRaw(OutputBindingEdge) }
const nodeCreationCandidates: WorkbenchNodeCreationCandidate[] = [
  { id: 'asset', label: '资产', description: '创建可编辑的昵称、Prompt 与图片资产', kind: 'asset', data: {} },
  { id: 'shot', label: '镜头', description: '创建一个可编辑的镜头生产节点', kind: 'shot', data: {} },
  { id: 'watermark', label: '创建水印', description: '创建水印配置节点', kind: 'watermark', data: {} },
  { id: 'operation:video_composer', label: '视频合成器', description: '创建成片合成节点', kind: 'video_composer', data: {} },
]
const connectionPicker = ref<{
  x: number
  y: number
  position: Point
  origin: WorkbenchConnectionOrigin
  options: CompatibleNodeCreation[]
  accentClass: string
} | null>(null)
const projectDefaults = computed(() => ({
  aspectRatio: SHOT_ASPECT_RATIOS.includes(props.aspectRatio as ShotAspectRatio) ? props.aspectRatio as ShotAspectRatio : '9:16',
  resolution: SHOT_RESOLUTIONS.includes(props.resolution as ShotResolution) ? props.resolution as ShotResolution : '720p',
}))
const visibleStoreNodes = computed(() => store.nodes.filter(item => (item.data.ui as Record<string, unknown> | undefined)?.hidden !== true))
const visibleNodeKeys = computed(() => new Set(visibleStoreNodes.value.map(item => item.key)))
const visibleStoreEdges = computed(() => store.edges.filter(item => visibleNodeKeys.value.has(item.source) && visibleNodeKeys.value.has(item.target)))
const flowNodes = computed<Node[]>(() => visibleStoreNodes.value.map(item => ({
  id: item.key, type: item.kind, position: item.position, zIndex: item.zIndex, selected: store.selectedNodeKeys.includes(item.key),
  ...(item.size ? { dimensions: { ...item.size }, style: { width: `${item.size.width}px`, height: `${item.size.height}px` } } : {}),
  data: {
    ...item.data,
    kind: item.kind,
    title: item.title,
    status: item.status,
    ...(item.kind === 'asset' ? { generate_capability: capabilities.value.generate_asset } : {}),
    ...(item.kind === 'shot' ? { generate_capability: capabilities.value.generate_video, project_defaults: projectDefaults.value } : {}),
    ...(() => {
      const editor = promptEditorForNode(item, promptEditors.value)
      return editor
        ? { prompt_editor: editor, prompt_editor_open: promptEditorNodeKey.value === item.key }
        : { prompt_editor: null, prompt_editor_open: false }
    })(),
    ...(item.kind === 'watermark' ? { apply_capability: capabilities.value.apply_watermark, capability_key: 'apply_watermark' } : {}),
    ...(item.kind === 'video_composer' ? { compose_capability: capabilities.value.compose_video, capability_key: 'compose_video' } : {}),
    ...(item.kind === 'section' ? { drop_candidate: sectionDropTargetKey.value === item.key } : {}),
  },
})))
const flowEdges = computed<Edge[]>(() => visibleStoreEdges.value.map((item) => {
  const handles = canonicalEdgeHandles(item)
  return {
    id: item.key,
    source: item.source,
    target: item.target,
    type: item.type,
    selected: store.selectedEdgeKeys.includes(item.key),
    sourceHandle: handles.sourceHandle,
    targetHandle: handles.targetHandle,
  }
}))
const panModeActive = computed(() => canvasTool.value === 'pan' || spacePanActive.value)
const interactionState = computed(() => workbenchInteractionState(false, panModeActive.value))
const hasDeletableSelection = computed(() => store.selectedNodeKeys.some(key => nodeCapabilities(store.nodeByKey(key)?.kind).deletable))
const canCopy = computed(() => store.selectedNodeKeys.length === 1 && nodeCapabilities(store.nodeByKey(store.selectedNodeKeys[0])?.kind).copyable)
const selectedSectionMembers = computed(() => store.selectedNodeKeys.map(key => store.nodeByKey(key)).filter((item): item is WorkbenchNode => Boolean(item && item.kind !== 'section')))
const canCreateSection = computed(() => selectedSectionMembers.value.length >= 2)
const selectedNodes = computed(() => store.selectedNodeKeys.flatMap(key => {
  const node = store.nodeByKey(key)
  return node ? [node] : []
}))
const runState = computed(() => selectedRunState(selectedNodes.value, capabilities.value))

function canonicalEdgeHandles(edge: WorkbenchEdge) {
  const source = store.nodeByKey(edge.source)
  const target = store.nodeByKey(edge.target)
  const sourceHandleIsValid = workbenchNodeHandles(source?.kind ?? 'unsupported', source?.data).source
    .some(handle => handle.id === edge.sourceHandle)
  const targetHandleIsValid = workbenchNodeHandles(target?.kind ?? 'unsupported', target?.data).target
    .some(handle => handle.id === edge.targetHandle)
  if (sourceHandleIsValid && targetHandleIsValid) {
    return { sourceHandle: edge.sourceHandle || undefined, targetHandle: edge.targetHandle || undefined }
  }
  if (edge.type === 'asset_reference') return { sourceHandle: 'asset-output', targetHandle: 'asset-input' }
  if (edge.type === 'shot_sequence') return { sourceHandle: 'sequence-output', targetHandle: 'sequence-input' }
  if (edge.type === 'output_binding') {
    if (source?.kind === 'watermark') return { sourceHandle: 'watermark-output', targetHandle: 'watermark-input' }
    if (target?.kind === 'watermark') return { sourceHandle: 'output-output', targetHandle: 'watermark-video-input' }
    if (target?.kind === 'video_result') return { sourceHandle: 'output-output', targetHandle: 'output-input' }
    if (target?.kind === 'video_composer') {
      if (source?.kind === 'shot') return { sourceHandle: 'sequence-output', targetHandle: 'shot-input' }
      return { sourceHandle: 'output-output', targetHandle: 'video-input' }
    }
  }
  return {
    sourceHandle: edge.sourceHandle || undefined,
    targetHandle: edge.targetHandle || undefined,
  }
}

provide(workbenchPromptEditorKey, {
  close(nodeKey) {
    if (promptEditorNodeKey.value === nodeKey) promptEditorNodeKey.value = null
  },
  async focusReference(nodeKey) {
    if (!getNodes.value.some(node => node.id === nodeKey)) return
    await fitView({
      nodes: [nodeKey],
      padding: 0.4,
      minZoom: 0.5,
      maxZoom: 1.25,
      duration: 260,
    })
  },
  removeReference(edgeKey) {
    void store.removeReferenceEdge(edgeKey)
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
let keyboardSource: KeyboardHandleActivation | null = null
let pointerConnectionOrigin: WorkbenchConnectionOrigin | null = null
let pointerConnectionCompleted = false

function activateKeyboardHandle(handle: KeyboardHandleActivation) {
  if (handle.type === 'source') {
    if (!nodeExposesHandle(store.nodeByKey(handle.nodeId), handle.handleId, 'source')) {
      keyboardSource = null
      keyboardStatus.value = '输出端口不可用，请重新选择'
      return
    }
    keyboardSource = handle
    keyboardStatus.value = `已选择 ${handle.nodeId} 的输出端口，请选择兼容的输入端口`
    return
  }
  if (!keyboardSource) {
    keyboardStatus.value = '请先选择一个输出端口'
    return
  }
  const source = keyboardSource
  keyboardSource = null
  if (!nodeExposesHandle(store.nodeByKey(source.nodeId), source.handleId, 'source')) {
    keyboardStatus.value = '已选择的输出端口已失效，请重新选择'
    return
  }
  if (!nodeExposesHandle(store.nodeByKey(handle.nodeId), handle.handleId, 'target')) {
    keyboardStatus.value = '目标输入端口不可用，请重新选择'
    return
  }
  const connected = store.connectMediaNode(source.nodeId, handle.nodeId, {
    sourceHandle: source.handleId,
    targetHandle: handle.handleId,
  })
  keyboardStatus.value = connected ? '连线已创建' : '连线创建失败'
}

function cancelKeyboardConnection() {
  keyboardSource = null
  keyboardStatus.value = '已取消键盘连线'
}

provide(workbenchKeyboardConnectorKey, {
  activateHandle: activateKeyboardHandle,
  cancel: cancelKeyboardConnection,
})

function canvasNodeSize(item: WorkbenchNode) {
  const rendered = getNodes.value.find(candidate => candidate.id === item.key)?.dimensions
  if (rendered && rendered.width > 0 && rendered.height > 0) return { width: rendered.width, height: rendered.height }
  if (item.size) return item.size
  if (item.kind === 'shot') return { width: 360, height: 520 }
  if (item.kind === 'video_result') return { width: 360, height: 300 }
  if (item.kind === 'watermark') return { width: 360, height: 300 }
  if (item.kind === 'video_composer') return { width: 390, height: 420 }
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
  if (!sameSelection(next, store.selectedNodeKeys)) {
    store.selectNodes(next)
    if (next.length !== 1 || !promptEditorNodeKey.value || !next.includes(promptEditorNodeKey.value))
      promptEditorNodeKey.value = null
  }
}
function rememberSelectionIntent(event: PointerEvent) {
  if (event.button !== 0 || !(event.target instanceof Element)) {
    selectionIntent = null
    return
  }
  if (isInteractiveSelectionTarget(event.target)) {
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
    promptEditorNodeKey.value = null
    void nextTick(() => { suppressNativeSelectionChanges = false })
    return
  }
  const nextSelection = selectionAfterNodeClick(intent.before, intent.key, intent.additive)
  applyAuthoritativeSelection(nextSelection)
  const selectedNode = nextSelection.length === 1 ? store.nodeByKey(nextSelection[0]) : null
  promptEditorNodeKey.value = selectedNode && canvasTool.value === 'select'
    && promptEditorForNode(selectedNode, promptEditors.value)
    ? selectedNode.key
    : null
}
function applyAuthoritativeSelection(keys: string[]) {
  suppressNativeSelectionChanges = true
  store.selectNodes(keys)
  void nextTick(() => { suppressNativeSelectionChanges = false })
}
function connectNodes(connection: Connection) {
  pointerConnectionCompleted = true
  if (connection.source && connection.target) {
    store.connectMediaNode(connection.source, connection.target, {
      sourceHandle: connection.sourceHandle,
      targetHandle: connection.targetHandle,
    })
  }
}
function handleConnectStart(params: OnConnectStartParams) {
  connectionPicker.value = null
  pointerConnectionCompleted = false
  pointerConnectionOrigin = params.nodeId && params.handleId && (params.handleType === 'source' || params.handleType === 'target')
    ? { nodeId: params.nodeId, handleId: params.handleId, handleType: params.handleType }
    : null
}
function connectionEndPoint(event: MouseEvent | TouchEvent) {
  if ('changedTouches' in event) {
    const touch = event.changedTouches[0]
    return touch ? { x: touch.clientX, y: touch.clientY } : null
  }
  return { x: event.clientX, y: event.clientY }
}
function handleConnectEnd(event?: MouseEvent | TouchEvent) {
  const origin = pointerConnectionOrigin
  pointerConnectionOrigin = null
  if (!origin || pointerConnectionCompleted || !event) return
  const eventTarget = event.target
  if (eventTarget instanceof Element && eventTarget.closest('.vue-flow__handle, .vue-flow__node')) return
  const point = connectionEndPoint(event)
  const originNode = store.nodeByKey(origin.nodeId)
  if (!point || !originNode) return
  const options = compatibleNodeCreations(origin, originNode, nodeCreationCandidates)
  if (!options.length) return
  const originHandle = workbenchNodeHandles(originNode.kind, originNode.data)[origin.handleType]
    .find(handle => handle.id === origin.handleId)
  connectionPicker.value = {
    x: point.x,
    y: point.y,
    position: screenToFlowCoordinate(point),
    origin,
    options,
    accentClass: originHandle?.className.replace('workbench-handle--', 'workbench-connection-picker--') ?? '',
  }
}
async function createCompatibleNode(option: CompatibleNodeCreation) {
  const picker = connectionPicker.value
  if (!picker) return
  connectionPicker.value = null
  const position = {
    x: Math.round(picker.position.x + (picker.origin.handleType === 'source' ? 18 : -370)),
    y: Math.round(picker.position.y - 100),
  }
  const created = option.candidate.id === 'asset'
    ? await store.addEmptyAsset(position)
    : option.candidate.id === 'shot'
      ? await store.addShot(position)
      : option.candidate.id === 'watermark'
        ? addWatermark(position)
        : option.candidate.id === 'operation:video_composer'
          ? addVideoComposer(position)
          : null
  if (!created) return
  if (picker.origin.handleType === 'source') {
    store.connectMediaNode(picker.origin.nodeId, created.key, {
      sourceHandle: picker.origin.handleId,
      targetHandle: option.candidateHandleId,
    })
  } else {
    store.connectMediaNode(created.key, picker.origin.nodeId, {
      sourceHandle: option.candidateHandleId,
      targetHandle: picker.origin.handleId,
    })
  }
}
function clearPane() {
  connectionPicker.value = null
  store.clearSelection()
}
function canvasSize() { const canvas = document.getElementById('novel-workbench'); const bounds = canvas?.getBoundingClientRect(); return { width: Math.max(1, bounds?.width || window.innerWidth), height: Math.max(1, bounds?.height || window.innerHeight) } }
function visibleNodePosition(size: NodeSize) {
  const bounds = vueFlowRef.value?.getBoundingClientRect()
  if (!bounds || !isWorkbenchFlowReady(bounds)) return { x: 80, y: 80 }
  return screenToFlowCoordinate(screenPointForCenteredNode(bounds, size))
}
async function ensureNodeVisible(key: string) {
  await nextTick()
  if (!getNodes.value.some(node => node.id === key)) return
  store.viewport = getViewport()
  saveWorkbenchViewport(String(props.chapterId), store.viewport, canvasSize())
}
async function addShot() {
  const created = await store.addShot(visibleNodePosition({ width: 360, height: 520 }))
  if (created) await ensureNodeVisible(created.key)
}
function addNote() {
  const created = store.addNote(visibleNodePosition({ width: 320, height: 220 }))
  void ensureNodeVisible(created.key)
}
function addWatermark(position = visibleNodePosition({ width: 360, height: 300 })) {
  const created = store.addWatermark(position)
  void ensureNodeVisible(created.key)
  return created
}
function addVideoComposer(position = visibleNodePosition({ width: 390, height: 420 })) {
  const created = store.addVideoComposer(position)
  void ensureNodeVisible(created.key)
  return created
}
async function addAsset() {
  const created = await store.addEmptyAsset(visibleNodePosition({ width: 520, height: 680 }))
  if (created) await ensureNodeVisible(created.key)
}
async function reuseAsset(assetId: number) {
  const created = await store.reuseAsset(assetId, visibleNodePosition({ width: 520, height: 680 }))
  if (created) await ensureNodeVisible(created.key)
}
async function uploadMedia(kind: Extract<WorkbenchNodeKind, 'image_media' | 'video_media' | 'audio_media'>, file: File) {
  const size = kind === 'audio_media' ? { width: 420, height: 170 } : kind === 'image_media' ? { width: 520, height: 360 } : { width: 360, height: 340 }
  try {
    const created = kind === 'image_media'
      ? await store.uploadImageAsset(file, visibleNodePosition(size))
      : await store.uploadMedia(kind, file, visibleNodePosition(size))
    if (created) await ensureNodeVisible(created.key)
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '媒体上传失败')
  }
}
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
  const { height } = canvasSize()
  const measuredSizes = Object.fromEntries(getNodes.value.flatMap((item) => {
    const { width, height } = item.dimensions
    return width > 0 && height > 0 ? [[item.id, { width, height } satisfies NodeSize]] : []
  }))
  const fixedNodeKeys = new Set(store.nodes
    .filter(node => node.zIndex >= 1_000_000 || (node.data.ui as Record<string, unknown> | undefined)?.locked === true)
    .map(node => node.key))
  const positions = buildWorkbenchGroupedAutoLayout(visibleStoreNodes.value, visibleStoreEdges.value, {
    sizes: measuredSizes,
    maxColumnHeight: Math.max(1100, height * 2.2),
    fixedNodeKeys,
  })
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
async function runSelected() {
  if (!runState.value.enabled) return
  generating.value = true
  try {
    for (const key of runState.value.runnableKeys) {
      const command = nodeRunRegistry.commands.get(key)
      if (command?.enabled.value) {
        await command.run()
        continue
      }
      const node = store.nodeByKey(key)
      if (node?.kind === 'asset') await store.generateAsset(node.id)
      if (node?.kind === 'shot') {
        const scene = node.data.scene as import('@/types').Scene
        const config = normalizeShotConfig(scene, projectDefaults.value)
        const modelType = Number(config.modelType ?? store.modelOptions[0]?.value)
        if (!Number.isFinite(modelType)) throw new Error('当前没有可用的视频模型')
        const model = store.videoModelOptions.find(item => item.config_id === modelType)
        await store.generateVideo(node.id, modelType, shotGenerationOptions(config, model?.capabilities))
      }
    }
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '运行所选配置失败')
  } finally {
    generating.value = false
  }
}
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

async function restoreViewport() {
  if (restoredViewportChapterId.value === props.chapterId) return
  const bounds = vueFlowRef.value?.getBoundingClientRect()
  if (!bounds || !isWorkbenchFlowReady(bounds)) return
  restoredViewportChapterId.value = props.chapterId
  const workspaceKey = String(props.chapterId)
  const saved = loadWorkbenchViewport(workspaceKey, bounds)
  if (saved) {
    await setViewport(saved)
  } else if (store.nodes.length) {
    await fitView({ padding: 0.12, minZoom: WORKBENCH_MIN_ZOOM, maxZoom: 0.85, duration: 0 })
  }
  store.viewport = getViewport()
  saveWorkbenchViewport(workspaceKey, store.viewport, bounds)
}

onMounted(async () => {
  window.addEventListener('keydown', handleKeydown); window.addEventListener('keyup', handleKeyup)
  try {
    const capabilityRequest = api.workbenchCapabilities().catch(() => null)
    await store.load(props.novelId, props.chapterId)
    const capabilityResponse = await capabilityRequest
    if (capabilityResponse) capabilities.value = capabilityResponse.data
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '工作区加载失败')
  }
})
onBeforeUnmount(() => { store.cancelPendingWork(); stopSelectionAutoPan(); window.removeEventListener('keydown', handleKeydown); window.removeEventListener('keyup', handleKeyup) })
</script>

<template>
  <main class="viral-workbench-page" @pointerdown.capture="rememberSelectionIntent" @click.capture="applySelectionIntent">
    <div v-if="store.loading" class="workbench-state" role="status">正在加载工作区…</div>
    <VueFlow v-else :id="WORKBENCH_FLOW_ID" class="viral-workbench-canvas" :class="{ 'is-pan-mode': interactionState.panOnDrag, 'is-manual-pan-mode': canvasTool === 'pan' }" aria-label="小说视频创作画布" :nodes="flowNodes" :edges="flowEdges" :node-types="nodeTypes" :edge-types="edgeTypes" :default-viewport="store.viewport" :min-zoom="WORKBENCH_MIN_ZOOM" :max-zoom="WORKBENCH_MAX_ZOOM" :pan-on-drag="interactionState.panOnDrag" :pan-on-scroll="true" :pan-on-scroll-mode="PanOnScrollMode.Vertical" :zoom-on-scroll="false" :zoom-on-pinch="false" :zoom-activation-key-code="zoomActivationKeyCode" :nodes-draggable="interactionState.nodesDraggable" :nodes-connectable="interactionState.nodesConnectable" :elements-selectable="interactionState.elementsSelectable" :select-nodes-on-drag="interactionState.selectNodesOnDrag" :selection-key-code="!interactionState.panOnDrag" :multi-selection-key-code="['Meta', 'Control', 'Shift']" :selection-mode="SelectionMode.Partial" :delete-key-code="null" no-wheel-class-name="nowheel" pan-activation-key-code="Space" @nodes-initialized="restoreViewport" @node-drag-start="nodeDragStart" @node-drag="nodeDrag" @node-drag-stop="nodeDragStop" @nodes-change="handleNodesChange" @pane-click="clearPane" @selection-start="startSelectionAutoPan" @selection-end="stopSelectionAutoPan" @move-end="moveEnd" @connect="connectNodes" @connect-start="handleConnectStart" @connect-end="handleConnectEnd">
      <Background variant="lines" color="#2b2926" :gap="38" :line-width="1" />
      <MiniMap aria-hidden="true" :tabindex="-1" pannable zoomable />
      <Controls position="bottom-right" />
      <CanvasToolSwitcher v-model="canvasTool" />
      <WorkbenchToolbar :running="generating" :can-undo="store.canUndo" :can-redo="store.canRedo" :has-selection="hasDeletableSelection" :can-copy="canCopy" :can-paste="Boolean(store.clipboardNode)" :can-create-section="canCreateSection" :run-state="runState" watermark-enabled composer-enabled @add-shot="addShot" @add-note="addNote" @add-asset="addAsset" @reuse-asset="projectAssetPickerOpen = true" @add-watermark="addWatermark" @add-composer="addVideoComposer" @upload-image="uploadMedia('image_media', $event)" @upload-video="uploadMedia('video_media', $event)" @upload-audio="uploadMedia('audio_media', $event)" @create-section="createSection" @run-selected="runSelected" @delete-selection="store.deleteSelection" @copy="store.copySelection" @paste="store.paste" @undo="undoCanvasAction" @redo="redoCanvasAction" @auto-arrange="autoArrange" />
      <div class="workbench-status-stack"><WorkbenchRunStatus :status="generating ? 'RUNNING' : 'IDLE'" :progress="generating ? 0 : undefined" /></div>
      <ConnectionNodePicker v-if="connectionPicker" :options="connectionPicker.options" :x="connectionPicker.x" :y="connectionPicker.y" :accent-class="connectionPicker.accentClass" @select="createCompatibleNode" @close="connectionPicker = null" />
      <p class="workbench-keyboard-status" role="status" aria-label="键盘连线状态" aria-live="polite">{{ keyboardStatus }}</p>
      <ProjectAssetPicker :open="projectAssetPickerOpen" :novel-id="props.novelId" :excluded-ids="store.assets.map(asset => asset.id)" @close="projectAssetPickerOpen = false" @choose="reuseAsset($event.id)" />
      <div v-if="store.nodes.length === 0" class="workbench-empty" role="status"><span>画布还是空的</span><AppButton type="button" @click="addShot">添加第一个镜头</AppButton></div>
    </VueFlow>
  </main>
</template>
