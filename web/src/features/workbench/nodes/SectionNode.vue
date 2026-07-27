<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core';
import { Layers3, Minimize2, MoreVertical, Palette, Trash2 } from 'lucide-vue-next';
import { computed, inject, ref } from 'vue';
import { workbenchSectionActionsKey } from '../interaction/sectionActions';
import { useWorkbenchStore } from '../store/workbenchStore';

const props = defineProps<NodeProps>();

const store = useWorkbenchStore();
const sectionActions = inject(workbenchSectionActionsKey, null);
const saving = ref(false);
const error = ref('');
const previewedColor = ref('');
const detailsOpen = ref(false);
const color = computed(() => previewedColor.value || (typeof props.data.color === 'string' ? props.data.color : '#31558f'));
const description = computed(() => typeof props.data.description === 'string' ? props.data.description : '');
const memberCount = computed(() => Array.isArray(props.data.node_keys) ? props.data.node_keys.length : 0);
const backgroundStyle = computed(() => ({
  '--workbench-section-color': color.value,
  'background-color': `${color.value}20`,
  'border-color': `${color.value}78`,
}));

function previewColor(event: Event) {
  const nextColor = (event.target as HTMLInputElement).value;
  error.value = '';
  previewedColor.value = nextColor;
  store.updateNodeDraft(props.id, { color: nextColor });
}

async function saveColor() {
  saving.value = true;
  try {
    await store.flushNodeDraft(props.id);
    previewedColor.value = '';
  }
  catch (reason) {
    error.value = reason instanceof Error ? reason.message : '分区颜色保存失败';
  }
  finally {
    saving.value = false;
  }
}

function updateDescription(event: Event) {
  store.updateNodeDraft(props.id, { description: (event.target as HTMLTextAreaElement).value });
}

async function saveDescription() {
  error.value = '';
  saving.value = true;
  try {
    await store.flushNodeDraft(props.id);
  }
  catch (reason) {
    error.value = reason instanceof Error ? reason.message : '分区说明保存失败';
  }
  finally {
    saving.value = false;
  }
}

async function deleteSection() {
  error.value = '';
  try {
    store.selectNode(props.id);
    await store.deleteSelection();
  }
  catch (reason) {
    error.value = reason instanceof Error ? reason.message : '分区删除失败';
  }
}

async function fitToContent() {
  error.value = '';
  try {
    await sectionActions?.fitToContent(props.id);
  }
  catch (reason) {
    error.value = reason instanceof Error ? reason.message : '分区适配内容失败';
  }
}
</script>

<template>
  <section class="workbench-section" :class="{ 'is-selected': selected, 'is-drop-target': data.drop_candidate === true }" :style="backgroundStyle" :aria-label="`${data.title || '画布分区'}，包含 ${memberCount} 个节点`">
    <div v-if="selected" class="workbench-section__toolbar nodrag nowheel" role="toolbar" aria-label="分区操作" @pointerdown.stop @click.stop>
      <button type="button" aria-label="删除分区" title="删除分区（不会删除内部节点）" @click="deleteSection">
        <Trash2 :size="17" aria-hidden="true" />
      </button>
      <label class="workbench-section__color-control" title="分区背景颜色">
        <Palette :size="17" aria-hidden="true" />
        <input type="color" :value="color" :disabled="saving" aria-label="修改分区颜色" @input="previewColor" @change="saveColor">
      </label>
      <button type="button" aria-label="重新包裹内部节点" title="重新包裹内部节点" :disabled="memberCount === 0" @click="fitToContent">
        <Minimize2 :size="17" aria-hidden="true" />
      </button>
      <button type="button" aria-label="分区更多设置" title="更多设置" :class="{ 'is-active': detailsOpen }" @click="detailsOpen = !detailsOpen">
        <MoreVertical :size="17" aria-hidden="true" />
      </button>
    </div>
    <header title="拖动节点进入分区可加入，拖出分区可移除；拖动标题栏可移动整个分区">
      <Layers3 :size="16" aria-hidden="true" />
      <strong>{{ data.title || '画布分区' }}</strong>
      <span>{{ memberCount }} 个节点</span>
      <span v-if="selected" class="workbench-section__membership-hint">拖入加入 · 拖出移除</span>
    </header>
    <textarea
      v-if="selected && detailsOpen"
      class="workbench-section__description nodrag nowheel"
      :value="description"
      maxlength="2000"
      aria-label="分区文字说明"
      placeholder="添加分区说明…"
      @input="updateDescription"
      @blur="saveDescription"
      @keydown.stop
    />
    <p v-else-if="description" class="workbench-section__description-text">
      {{ description }}
    </p>
    <p v-if="error" class="workbench-section__error" role="alert">
      {{ error }}
    </p>
  </section>
</template>
