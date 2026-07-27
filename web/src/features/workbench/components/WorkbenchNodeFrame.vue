<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { Handle, Position } from '@vue-flow/core'
import {
  Ban,
  BookOpenText,
  Box,
  ChevronDown,
  ChevronUp,
  Clapperboard,
  Droplet,
  FileAudio2,
  FileImage,
  FileVideo2,
  Film,
  Info,
  Layers3,
  Palette,
  Pin,
  ScanFace,
  StickyNote,
  Trash2,
  Volume2,
} from 'lucide-vue-next'
import { computed, inject, ref } from 'vue'
import { nodeCapabilities } from '../config/nodeCapabilities'
import { configuredNodePorts, workbenchNodeHandles } from '../graph/handleCapabilities'
import { isPinnedNode, nextPinnedNodeZIndex, nextRegularNodeZIndex } from '../graph/nodeLayering'
import { workbenchKeyboardConnectorKey } from '../keyboard/keyboardConnection'
import { useWorkbenchStore } from '../store/workbenchStore'
import type { WorkbenchNodeData, WorkbenchNodeKind } from '../types/workbenchTypes'
import NodeInfoPanel from './NodeInfoPanel.vue'

interface FrameData extends WorkbenchNodeData {
  title?: string
  kind?: WorkbenchNodeKind
  status?: string
}

const props = withDefaults(defineProps<{
  id: string
  type?: string
  position?: unknown
  dimensions?: unknown
  dragging?: boolean
  resizing?: boolean
  zIndex?: number
  events?: unknown
  data: FrameData
  selected?: boolean
  connectable?: NodeProps['connectable']
}>(), { selected: false, connectable: true })
const keyboardConnector = inject(workbenchKeyboardConnectorKey, null)
const store = useWorkbenchStore()
const infoOpen = ref(false)
const paletteOpen = ref(false)
const actionError = ref('')
const markerColors = ['#a995ff', '#df7f73', '#dfb75f', '#70a98a', '#6d99c7', '#d584b8']

const kind = computed(() => (props.data.kind ?? 'unsupported') as WorkbenchNodeKind)
const liveNode = computed(() => store.nodeByKey(props.id))
const nodeUi = computed<Record<string, unknown>>(() => {
  const value = liveNode.value?.data.ui
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
})
const collapsed = computed(() => nodeUi.value.collapsed === true)
const ignored = computed(() => nodeUi.value.ignored === true)
const markerColor = computed(() => typeof nodeUi.value.color === 'string' ? nodeUi.value.color : '')
const canDelete = computed(() => nodeCapabilities(kind.value).deletable)
const pinned = computed(() => isPinnedNode(liveNode.value))
const icon = computed(() => ({
  chapter: BookOpenText,
  asset: Box,
  audio_reference: Volume2,
  digital_human: ScanFace,
  image_media: FileImage,
  video_media: FileVideo2,
  audio_media: FileAudio2,
  shot: Clapperboard,
  video_result: FileVideo2,
  watermark: Droplet,
  video_composer: Film,
  section: Layers3,
  note: StickyNote,
  unsupported: Box,
})[kind.value])
const targetHandles = computed(() => workbenchNodeHandles(kind.value, props.data as WorkbenchNodeData).target)
const sourceHandles = computed(() => workbenchNodeHandles(kind.value, props.data as WorkbenchNodeData).source)
const configuredTargetHandleIds = computed(() => new Set(
  configuredNodePorts(props.data as WorkbenchNodeData)
    .filter(handle => handle.type === 'target')
    .map(handle => handle.id),
))

function handleTop(index: number, count: number) {
  return `${count === 1 ? 50 : 20 + (index * 60) / (count - 1)}%`
}

function handleKeydown(event: KeyboardEvent, handleId: string, type: 'source' | 'target') {
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    keyboardConnector?.cancel()
    return
  }
  if (event.key !== 'Enter' && event.key !== ' ') return
  event.preventDefault()
  event.stopPropagation()
  keyboardConnector?.activateHandle({ nodeId: props.id, handleId, type })
}

async function updateUi(patch: Record<string, unknown>) {
  actionError.value = ''
  store.checkpoint()
  store.updateNodeUi(props.id, { ...nodeUi.value, ...patch })
  try {
    await store.flushLayout()
  }
  catch (error) {
    actionError.value = error instanceof Error ? error.message : '节点设置保存失败'
    paletteOpen.value = false
  }
}

function previewCustomColor(event: Event) {
  store.updateNodeUi(props.id, { ...nodeUi.value, color: (event.target as HTMLInputElement).value })
}

function beginCustomColor() {
  store.checkpoint()
}

function saveCustomColor(event: Event) {
  paletteOpen.value = false
  void updateUi({ color: (event.target as HTMLInputElement).value })
}

async function deleteNode() {
  if (!canDelete.value) return
  actionError.value = ''
  store.selectNode(props.id)
  try {
    await store.deleteSelection()
  }
  catch (error) {
    actionError.value = error instanceof Error ? error.message : '删除节点失败'
    infoOpen.value = true
  }
}

async function togglePinned() {
  const node = liveNode.value
  if (!node) return
  actionError.value = ''
  store.checkpoint()
  const zIndex = pinned.value
    ? nextRegularNodeZIndex(store.nodes.filter(item => item.key !== props.id))
    : nextPinnedNodeZIndex(store.nodes)
  store.updateNodeLayout(props.id, node.position, node.size, zIndex)
  try {
    await store.flushLayout()
  }
  catch (error) {
    actionError.value = error instanceof Error ? error.message : '节点层级保存失败'
  }
}

function toggleInfo() {
  infoOpen.value = !infoOpen.value
  paletteOpen.value = false
}

function togglePalette() {
  paletteOpen.value = !paletteOpen.value
  infoOpen.value = false
}
</script>

<template>
  <article
    class="workbench-node-frame"
    :class="{ 'is-selected': selected, 'is-collapsed': collapsed, 'is-ignored': ignored, 'has-marker': markerColor }"
    :style="markerColor ? { '--workbench-node-marker': markerColor } : undefined"
    :aria-label="`${data.title || '未命名'}节点`"
  >
    <div v-if="selected" class="workbench-node-context nodrag nowheel" role="toolbar" :aria-label="`${data.title || '未命名'}节点操作`" @pointerdown.stop @click.stop>
      <button type="button" aria-label="删除选中节点" title="删除" :disabled="!canDelete" @click="deleteNode">
        <Trash2 :size="16" aria-hidden="true" />
      </button>
      <span class="workbench-node-context__divider" aria-hidden="true" />
      <button type="button" aria-label="查看节点信息" title="节点信息" :class="{ 'is-active': infoOpen }" @click="toggleInfo">
        <Info :size="16" aria-hidden="true" />
      </button>
      <slot name="toolbar-actions" />
      <button type="button" aria-label="设置节点背景颜色" title="背景颜色" :class="{ 'is-active': paletteOpen }" @click="togglePalette">
        <Palette class="workbench-node-context__palette-icon" :style="markerColor ? { color: markerColor } : undefined" :size="17" aria-hidden="true" />
      </button>
      <button type="button" :aria-label="pinned ? '取消固钉选中节点' : '固钉选中节点到最上层'" :title="pinned ? '取消固钉' : '固钉到最上层'" :class="{ 'is-active': pinned }" @click="togglePinned">
        <Pin :size="16" :fill="pinned ? 'currentColor' : 'none'" aria-hidden="true" />
      </button>
      <button type="button" :aria-label="collapsed ? '展开选中节点' : '收缩选中节点'" :title="collapsed ? '展开' : '收缩'" @click="updateUi({ collapsed: !collapsed })">
        <ChevronDown v-if="collapsed" :size="17" aria-hidden="true" />
        <ChevronUp v-else :size="17" aria-hidden="true" />
      </button>
      <button type="button" :aria-label="ignored ? '取消忽略选中节点' : '忽略选中节点'" :title="ignored ? '取消忽略' : '忽略'" :class="{ 'is-active': ignored }" @click="updateUi({ ignored: !ignored })">
        <Ban :size="16" aria-hidden="true" />
      </button>

      <div v-if="paletteOpen" class="workbench-node-context__popover workbench-node-context__palette" aria-label="节点背景颜色选项">
        <button v-for="color in markerColors" :key="color" type="button" :aria-label="`使用背景颜色 ${color}`" :style="{ background: color }" @click="updateUi({ color }); paletteOpen = false" />
        <label class="workbench-node-context__custom-color" title="自定义背景颜色">
          <span class="sr-only">自定义背景颜色</span>
          <input type="color" :value="markerColor || '#a995ff'" aria-label="自定义背景颜色" @pointerdown="beginCustomColor" @input="previewCustomColor" @change="saveCustomColor">
        </label>
        <button type="button" class="is-clear" aria-label="清除节点背景颜色" @click="updateUi({ color: '' }); paletteOpen = false">×</button>
      </div>
    </div>

    <NodeInfoPanel v-if="infoOpen && liveNode" :node="liveNode" :action-error="actionError" @close="infoOpen = false" />

    <Handle
      v-for="(handle, index) in targetHandles"
      :id="handle.id"
      :key="handle.id"
      type="target"
      :position="Position.Left"
      :connectable="connectable"
      class="workbench-handle"
      :class="handle.className"
      :style="{ top: handleTop(index, targetHandles.length) }"
      :aria-label="handle.label"
      :title="handle.label"
      role="button"
      :tabindex="0"
      @keydown="handleKeydown($event, handle.id, 'target')"
    />
    <span
      v-for="(handle, index) in targetHandles"
      v-show="configuredTargetHandleIds.has(handle.id)"
      :key="`${handle.id}-label`"
      class="workbench-handle-label workbench-handle-label--target"
      :style="{ top: handleTop(index, targetHandles.length) }"
      aria-hidden="true"
    >
      {{ handle.label }}<small v-if="!handle.required">可选</small>
    </span>

    <header class="workbench-node-frame__header">
      <component :is="icon" :size="17" aria-hidden="true" />
      <span>{{ data.title || '未命名节点' }}</span>
      <span v-if="ignored" class="workbench-node-frame__ignored">已忽略</span>
      <span class="workbench-node-frame__status">{{ data.status || 'ready' }}</span>
    </header>
    <div v-if="!collapsed" class="workbench-node-frame__body nodrag">
      <slot>
        <span>{{ kind === 'unsupported' ? '暂不支持此节点类型' : '等待节点内容' }}</span>
      </slot>
    </div>

    <Handle
      v-for="(handle, index) in sourceHandles"
      :id="handle.id"
      :key="handle.id"
      type="source"
      :position="Position.Right"
      :connectable="connectable"
      class="workbench-handle"
      :class="handle.className"
      :style="{ top: handleTop(index, sourceHandles.length) }"
      :aria-label="handle.label"
      :title="handle.label"
      role="button"
      :tabindex="0"
      @keydown="handleKeydown($event, handle.id, 'source')"
    />
  </article>
</template>
