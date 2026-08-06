<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core';
import { Palette, StickyNote, Trash2 } from 'lucide-vue-next';
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import { useWorkbenchStore } from '../store/workbenchStore';

const props = defineProps<NodeProps>();

const store = useWorkbenchStore();
const saving = ref(false);
const error = ref('');
const textareaRef = ref<HTMLTextAreaElement | null>(null);
const layoutChanged = ref(false);
const content = computed(() => typeof props.data.content === 'string' ? props.data.content : '');
const previewedColor = ref('');
const color = computed(() => previewedColor.value || (typeof props.data.color === 'string' ? props.data.color : '#8d793d'));
const noteStyle = computed(() => ({ '--workbench-note-color': color.value }));

function resizeToContent() {
  const textarea = textareaRef.value;
  const node = store.nodeByKey(props.id);
  if (!textarea || !node)
    return;
  textarea.style.height = 'auto';
  const textareaHeight = Math.ceil(textarea.scrollHeight);
  textarea.style.height = `${textareaHeight}px`;
  const width = node.size?.width ?? 320;
  const height = Math.max(220, textareaHeight + 44);
  if (node.size?.width === width && node.size?.height === height)
    return;
  store.updateNodeLayout(props.id, node.position, { width, height }, node.zIndex);
  layoutChanged.value = true;
}

function updateContent(event: Event) {
  store.updateNodeDraft(props.id, { content: (event.target as HTMLTextAreaElement).value });
  resizeToContent();
}

async function saveContent() {
  error.value = '';
  saving.value = true;
  try {
    await store.flushNodeDraft(props.id);
    if (layoutChanged.value) {
      await store.flushLayout();
      layoutChanged.value = false;
    }
  }
  catch (reason) {
    error.value = reason instanceof Error ? reason.message : '便签保存失败';
  }
  finally {
    saving.value = false;
  }
}

onMounted(() => void nextTick(resizeToContent));
watch(content, () => void nextTick(resizeToContent));

function previewColor(event: Event) {
  const nextColor = (event.target as HTMLInputElement).value;
  previewedColor.value = nextColor;
  store.updateNodeDraft(props.id, { color: nextColor });
}

async function saveColor() {
  await saveContent();
  previewedColor.value = '';
}

async function deleteNote() {
  store.selectNode(props.id);
  try {
    await store.deleteSelection();
  }
  catch (reason) {
    error.value = reason instanceof Error ? reason.message : '便签删除失败';
  }
}
</script>

<template>
  <article class="workbench-note" :class="{ 'is-selected': selected }" :style="noteStyle" :aria-label="String(data.title || '便签')">
    <div v-if="selected" class="workbench-note__toolbar nodrag nowheel" role="toolbar" aria-label="便签操作" @pointerdown.stop @click.stop>
      <button type="button" aria-label="删除便签" title="删除便签" @click="deleteNote">
        <Trash2 :size="17" aria-hidden="true" />
      </button>
      <label title="便签背景颜色">
        <Palette :size="17" aria-hidden="true" />
        <input type="color" :value="color" :disabled="saving" aria-label="修改便签背景颜色" @input="previewColor" @change="saveColor">
      </label>
    </div>
    <header>
      <StickyNote :size="16" aria-hidden="true" />
      <strong>{{ data.title || '便签' }}</strong>
      <span v-if="saving">保存中…</span>
    </header>
    <textarea
      ref="textareaRef"
      class="nodrag nowheel"
      :value="content"
      maxlength="10000"
      aria-label="便签内容"
      placeholder="输入说明、备注或待办事项…"
      @input="updateContent"
      @blur="saveContent"
      @keydown.stop
    />
    <p v-if="error" role="alert">
      {{ error }}
    </p>
  </article>
</template>
