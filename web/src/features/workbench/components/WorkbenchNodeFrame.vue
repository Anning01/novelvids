<script setup lang="ts">
import type { WorkbenchNodeKind } from '../types/workbenchTypes'
import { Handle, Position } from '@vue-flow/core'
import { Ban, BookOpenText, Box, ChevronDown, ChevronUp, Clapperboard, FileVideo2, Info, Layers3, Palette, Pin, ScanFace, StickyNote, Trash2, Volume2 } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { useWorkbenchStore } from '../store/workbenchStore'
import NodeInfoPanel from './NodeInfoPanel.vue'

const props = defineProps<{ id: string; data: { title?: string; kind?: WorkbenchNodeKind; status?: string }; selected?: boolean; connectable?: unknown }>()
const store = useWorkbenchStore()
const infoOpen = ref(false)
const paletteOpen = ref(false)
const markerColors = ['#a995ff', '#df7f73', '#dfb75f', '#70a98a', '#6d99c7', '#d584b8']
const node = computed(() => store.nodeByKey(props.id))
const ui = computed(() => (node.value?.data.ui as Record<string, unknown>) || {})
const collapsed = computed(() => ui.value.collapsed === true)
const ignored = computed(() => ui.value.ignored === true)
const pinned = computed(() => (node.value?.zIndex || 0) >= 1_000_000)
const markerColor = computed(() => typeof ui.value.color === 'string' ? ui.value.color : '')
const icon = computed(() => ({ chapter: BookOpenText, asset: Box, audio_reference: Volume2, digital_human: ScanFace, shot: Clapperboard, video_result: FileVideo2, section: Layers3, note: StickyNote, unsupported: Box })[props.data.kind || 'unsupported'])
const hasTarget = computed(() => props.data.kind === 'shot' || props.data.kind === 'video_result')
const hasSource = computed(() => props.data.kind === 'chapter' || props.data.kind === 'asset' || props.data.kind === 'audio_reference' || props.data.kind === 'digital_human' || props.data.kind === 'shot')
const canDelete = computed(() => props.data.kind === 'shot' || props.data.kind === 'audio_reference' || props.data.kind === 'digital_human')

function updateUi(patch: Record<string, unknown>) { store.checkpoint(); store.updateNodeUi(props.id, { ...ui.value, ...patch }) }
function beginCustomColor() { store.checkpoint() }
function previewCustomColor(event: Event) { store.updateNodeUi(props.id, { ...ui.value, color: (event.target as HTMLInputElement).value }) }
function saveCustomColor(event: Event) { store.updateNodeUi(props.id, { ...ui.value, color: (event.target as HTMLInputElement).value }); paletteOpen.value = false }
function togglePin() { if (!node.value) return; store.checkpoint(); store.updateNodeLayout(props.id, node.value.position, node.value.size, pinned.value ? 1 : 1_000_000 + Math.max(0, ...store.nodes.map(item => item.zIndex))); void store.flushLayout() }
function toggleInfo() { infoOpen.value = !infoOpen.value; paletteOpen.value = false }
function togglePalette() { paletteOpen.value = !paletteOpen.value; infoOpen.value = false }
</script>

<template>
  <article class="workbench-node-frame" :class="{ 'is-selected': selected, 'is-collapsed': collapsed, 'is-ignored': ignored, 'has-marker': markerColor }" :style="markerColor ? { '--workbench-node-marker': markerColor } : undefined" :aria-label="`${data.title || '未命名'}节点`">
    <div v-if="selected" class="workbench-node-context nodrag nowheel" role="toolbar" :aria-label="`${data.title || '未命名'}节点操作`" @pointerdown.stop @click.stop>
      <button type="button" aria-label="删除选中节点" title="删除" :disabled="!canDelete" @click="store.deleteNodeKeys([props.id])"><Trash2 :size="16" aria-hidden="true" /></button>
      <span class="workbench-node-context__divider" aria-hidden="true" />
      <button type="button" aria-label="查看节点信息" title="节点信息" :class="{ 'is-active': infoOpen }" @click="toggleInfo"><Info :size="16" aria-hidden="true" /></button>
      <slot name="toolbar-actions" />
      <button type="button" aria-label="设置节点背景颜色" title="背景颜色" :class="{ 'is-active': paletteOpen }" @click="togglePalette"><Palette class="workbench-node-context__palette-icon" :size="17" :style="markerColor ? { color: markerColor } : undefined" aria-hidden="true" /></button>
      <button type="button" :aria-label="pinned ? '取消固钉选中节点' : '固钉选中节点到最上层'" :title="pinned ? '取消固钉' : '固钉到最上层'" :class="{ 'is-active': pinned }" @click="togglePin"><Pin :size="16" :fill="pinned ? 'currentColor' : 'none'" aria-hidden="true" /></button>
      <button type="button" :aria-label="collapsed ? '展开选中节点' : '收缩选中节点'" :title="collapsed ? '展开' : '收缩'" @click="updateUi({ collapsed: !collapsed })"><ChevronDown v-if="collapsed" :size="17" aria-hidden="true" /><ChevronUp v-else :size="17" aria-hidden="true" /></button>
      <button type="button" :aria-label="ignored ? '取消忽略选中节点' : '忽略选中节点'" :title="ignored ? '取消忽略' : '忽略'" :class="{ 'is-active': ignored }" @click="updateUi({ ignored: !ignored })"><Ban :size="16" aria-hidden="true" /></button>
      <div v-if="paletteOpen" class="workbench-node-context__popover workbench-node-context__palette" aria-label="节点背景颜色选项">
        <button v-for="color in markerColors" :key="color" type="button" :aria-label="`使用背景颜色 ${color}`" :style="{ background: color }" @click="updateUi({ color }); paletteOpen = false" />
        <label class="workbench-node-context__custom-color" title="自定义背景颜色"><span class="sr-only">自定义背景颜色</span><input type="color" :value="markerColor || '#a995ff'" aria-label="自定义背景颜色" @pointerdown="beginCustomColor" @input="previewCustomColor" @change="saveCustomColor"></label>
        <button type="button" class="is-clear" aria-label="清除节点背景颜色" @click="updateUi({ color: '' }); paletteOpen = false">×</button>
      </div>
    </div>
    <NodeInfoPanel v-if="infoOpen && node" :node="node" @close="infoOpen = false" />
    <Handle v-if="hasTarget" id="input" type="target" :position="Position.Left" :connectable="connectable !== false" class="workbench-handle" aria-label="输入连接点" />
    <header class="workbench-node-frame__header"><component :is="icon" :size="17" aria-hidden="true" /><span>{{ data.title || '未命名节点' }}</span><span v-if="ignored" class="workbench-node-frame__ignored">已忽略</span><span class="workbench-node-frame__status">{{ data.status || 'ready' }}</span></header>
    <div v-if="!collapsed" class="workbench-node-frame__body nodrag"><slot><span>等待节点内容</span></slot></div>
    <Handle v-if="hasSource" id="output" type="source" :position="Position.Right" :connectable="connectable !== false" class="workbench-handle" aria-label="输出连接点" />
  </article>
</template>
