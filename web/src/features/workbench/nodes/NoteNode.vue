<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { Palette, StickyNote, Trash2 } from 'lucide-vue-next'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useWorkbenchStore } from '../store/workbenchStore'

const props = defineProps<NodeProps>()
const store = useWorkbenchStore()
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const content = computed(() => typeof props.data.content === 'string' ? props.data.content : '')
const color = computed(() => typeof props.data.color === 'string' ? props.data.color : '#8d793d')
const noteStyle = computed(() => ({ '--workbench-note-color': color.value, overflow: 'visible' }))

function resizeToContent() {
  const textarea = textareaRef.value
  const item = store.nodeByKey(props.id)
  if (!textarea || !item) return
  textarea.style.height = 'auto'
  const textareaHeight = Math.ceil(textarea.scrollHeight)
  textarea.style.height = `${textareaHeight}px`
  const size = { width: item.size?.width ?? 320, height: Math.max(220, textareaHeight + 44) }
  if (item.size?.width !== size.width || item.size?.height !== size.height) store.updateNodeLayout(props.id, item.position, size, item.zIndex)
}
function updateContent(event: Event) { store.updateManualNodeData(props.id, { content: (event.target as HTMLTextAreaElement).value }); resizeToContent() }
function updateColor(event: Event) { store.updateManualNodeData(props.id, { color: (event.target as HTMLInputElement).value }) }
function beginEdit() { store.checkpoint() }
function save() { store.persistLayout() }
function deleteNote() { void store.deleteNodeKeys([props.id]) }
onMounted(() => void nextTick(resizeToContent))
watch(content, () => void nextTick(resizeToContent))
</script>

<template>
  <article class="workbench-note" :class="{ 'is-selected': selected }" :style="noteStyle" :aria-label="String(data.title || '便签')">
    <div v-if="selected" class="workbench-note__toolbar nodrag nowheel" role="toolbar" aria-label="便签操作" @pointerdown.stop @click.stop>
      <button type="button" aria-label="删除便签" title="删除便签" @click="deleteNote"><Trash2 :size="17" aria-hidden="true" /></button>
      <label title="便签背景颜色"><Palette :size="17" aria-hidden="true" /><input type="color" :value="color" aria-label="修改便签背景颜色" @pointerdown="beginEdit" @input="updateColor" @change="save"></label>
    </div>
    <header><StickyNote :size="16" aria-hidden="true" /><strong>{{ data.title || '便签' }}</strong></header>
    <textarea ref="textareaRef" class="nodrag nowheel" :value="content" maxlength="10000" aria-label="便签内容" placeholder="输入说明、备注或待办事项…" @focus="beginEdit" @input="updateContent" @blur="save" @keydown.stop />
  </article>
</template>
