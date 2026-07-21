<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { Layers3, Minimize2, MoreVertical, Palette, Trash2 } from 'lucide-vue-next'
import { computed, inject, ref } from 'vue'
import { workbenchSectionActionsKey } from '../interaction/sectionActions'
import { useWorkbenchStore } from '../store/workbenchStore'

const props = defineProps<NodeProps>()
const store = useWorkbenchStore()
const sectionActions = inject(workbenchSectionActionsKey, null)
const detailsOpen = ref(false)
const color = computed(() => typeof props.data.color === 'string' ? props.data.color : '#31558f')
const description = computed(() => typeof props.data.description === 'string' ? props.data.description : '')
const memberCount = computed(() => Array.isArray(props.data.node_keys) ? props.data.node_keys.length : 0)
const backgroundStyle = computed(() => ({ '--workbench-section-color': color.value, backgroundColor: `${color.value}20`, borderColor: `${color.value}78` }))

function updateColor(event: Event) { store.updateManualNodeData(props.id, { color: (event.target as HTMLInputElement).value }); store.persistLayout() }
function updateDescription(event: Event) { store.updateManualNodeData(props.id, { description: (event.target as HTMLTextAreaElement).value }) }
function deleteSection() { store.selectNode(props.id); void store.deleteSelection() }
function fitToContent() { void sectionActions?.fitToContent(props.id) }
</script>

<template>
  <section class="workbench-section" :class="{ 'is-selected': selected, 'is-drop-target': data.drop_candidate === true }" :style="backgroundStyle" :aria-label="`${data.title || '画布分区'}，包含 ${memberCount} 个节点`">
    <div v-if="selected" class="workbench-section__toolbar nodrag nowheel" role="toolbar" aria-label="分区操作" @pointerdown.stop @click.stop>
      <AppButton type="button" aria-label="删除分区" title="删除分区（不会删除内部节点）" @click="deleteSection"><Trash2 :size="17" aria-hidden="true" /></AppButton>
      <label class="workbench-section__color-control" title="分区背景颜色"><Palette :size="17" aria-hidden="true" /><input type="color" :value="color" aria-label="修改分区颜色" @input="updateColor"></label>
      <AppButton type="button" aria-label="重新包裹内部节点" title="重新包裹内部节点" :disabled="memberCount === 0" @click="fitToContent"><Minimize2 :size="17" aria-hidden="true" /></AppButton>
      <AppButton type="button" aria-label="分区更多设置" title="更多设置" :class="{ 'is-active': detailsOpen }" @click="detailsOpen = !detailsOpen"><MoreVertical :size="17" aria-hidden="true" /></AppButton>
    </div>
    <header title="拖动节点进入分区可加入，拖出分区可移除；拖动标题栏可移动整个分区"><Layers3 :size="16" aria-hidden="true" /><strong>{{ data.title || '画布分区' }}</strong><span>{{ memberCount }} 个节点</span><span v-if="selected" class="workbench-section__membership-hint">拖入加入 · 拖出移除</span></header>
    <textarea v-if="selected && detailsOpen" class="workbench-section__description nodrag nowheel" :value="description" maxlength="2000" aria-label="分区文字说明" placeholder="添加分区说明…" @input="updateDescription" @blur="store.persistLayout()" @keydown.stop />
    <p v-else-if="description" class="workbench-section__description-text">{{ description }}</p>
  </section>
</template>
