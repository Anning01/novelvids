<script setup lang="ts">
import type { WorkbenchNodeKind } from '../types/workbenchTypes'
import { Handle, Position } from '@vue-flow/core'
import { Ban, BookOpenText, Box, ChevronDown, ChevronUp, Clapperboard, FileVideo2, Palette, Pin, ScanFace, Trash2, Volume2 } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { useWorkbenchStore } from '../store/workbenchStore'

const props = defineProps<{ id: string; data: { title?: string; kind?: WorkbenchNodeKind; status?: string }; selected?: boolean; connectable?: unknown }>()
const store = useWorkbenchStore()
const paletteOpen = ref(false)
const markerColors = ['#a995ff', '#df7f73', '#dfb75f', '#70a98a', '#6d99c7', '#d584b8']
const node = computed(() => store.nodeByKey(props.id))
const ui = computed(() => (node.value?.data.ui as Record<string, unknown>) || {})
const collapsed = computed(() => ui.value.collapsed === true)
const ignored = computed(() => ui.value.ignored === true)
const pinned = computed(() => (node.value?.zIndex || 0) >= 1_000_000)
const markerColor = computed(() => typeof ui.value.color === 'string' ? ui.value.color : '')
const icon = computed(() => ({ chapter: BookOpenText, asset: Box, audio_reference: Volume2, digital_human: ScanFace, shot: Clapperboard, video_result: FileVideo2, unsupported: Box })[props.data.kind || 'unsupported'])
const hasTarget = computed(() => props.data.kind === 'shot' || props.data.kind === 'video_result')
const hasSource = computed(() => props.data.kind === 'chapter' || props.data.kind === 'asset' || props.data.kind === 'audio_reference' || props.data.kind === 'digital_human' || props.data.kind === 'shot')
const canDelete = computed(() => props.data.kind === 'shot' || props.data.kind === 'audio_reference' || props.data.kind === 'digital_human')

function updateUi(patch: Record<string, unknown>) { store.updateNodeUi(props.id, { ...ui.value, ...patch }) }
function togglePin() { if (!node.value) return; store.updateNodeLayout(props.id, node.value.position, node.value.size, pinned.value ? 1 : 1_000_000 + Math.max(0, ...store.nodes.map(item => item.zIndex))); store.flushLayout() }
</script>

<template>
  <article class="workbench-node-frame" :class="{ 'is-selected': selected, 'is-collapsed': collapsed, 'is-ignored': ignored, 'has-marker': markerColor }" :style="markerColor ? { '--workbench-node-marker': markerColor } : undefined" :aria-label="`${data.title || '未命名'}节点`">
    <div v-if="selected" class="workbench-node-context nodrag nowheel" role="toolbar" :aria-label="`${data.title || '未命名'}节点操作`" @pointerdown.stop @click.stop>
      <AppButton type="button" aria-label="删除选中节点" :disabled="!canDelete" @click="store.deleteSelection()"><Trash2 :size="16" /></AppButton>
      <span class="workbench-node-context__divider" />
      <AppButton type="button" aria-label="设置节点标记颜色" title="标记颜色" :class="{ 'is-active': paletteOpen }" @click="paletteOpen = !paletteOpen"><Palette :size="17" :style="markerColor ? { color: markerColor } : undefined" /></AppButton>
      <AppButton type="button" :aria-label="pinned ? '取消固钉' : '固钉到最上层'" :class="{ 'is-active': pinned }" @click="togglePin"><Pin :size="16" :fill="pinned ? 'currentColor' : 'none'" /></AppButton>
      <AppButton type="button" :aria-label="collapsed ? '展开节点' : '收缩节点'" @click="updateUi({ collapsed: !collapsed })"><ChevronDown v-if="collapsed" :size="17" /><ChevronUp v-else :size="17" /></AppButton>
      <AppButton type="button" :aria-label="ignored ? '取消忽略节点' : '忽略节点'" :class="{ 'is-active': ignored }" @click="updateUi({ ignored: !ignored })"><Ban :size="16" /></AppButton>
      <div v-if="paletteOpen" class="workbench-node-context__popover workbench-node-context__palette">
        <AppButton v-for="color in markerColors" :key="color" type="button" :aria-label="`标记颜色 ${color}`" :style="{ background: color }" @click="updateUi({ color }); paletteOpen = false" />
        <AppButton type="button" class="is-clear" aria-label="清除颜色" @click="updateUi({ color: '' }); paletteOpen = false">×</AppButton>
      </div>
    </div>
    <Handle v-if="hasTarget" id="input" type="target" :position="Position.Left" :connectable="connectable !== false" class="workbench-handle" aria-label="输入连接点" />
    <header class="workbench-node-frame__header"><component :is="icon" :size="17" /><span>{{ data.title || '未命名节点' }}</span><span v-if="ignored" class="workbench-node-frame__ignored">已忽略</span><span class="workbench-node-frame__status">{{ data.status || 'ready' }}</span></header>
    <div v-if="!collapsed" class="workbench-node-frame__body nodrag"><slot /></div>
    <Handle v-if="hasSource" id="output" type="source" :position="Position.Right" :connectable="connectable !== false" class="workbench-handle" aria-label="输出连接点" />
  </article>
</template>
