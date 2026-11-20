<script setup lang="ts">
import { tr } from '@/i18n'

import { ElPopover } from 'element-plus';
import type { NodeProps } from '@vue-flow/core';
import { Layers3, Minimize2, MoreVertical, Ungroup } from 'lucide-vue-next';
import { computed, inject, ref } from 'vue';
import WorkbenchColorPicker from '../components/WorkbenchColorPicker.vue'
import { DEFAULT_SECTION_COLOR } from '../graph/nodeAppearance'
import { workbenchSectionActionsKey } from '../interaction/sectionActions';
import { useWorkbenchStore } from '../store/workbenchStore';

const props = defineProps<NodeProps>();

const store = useWorkbenchStore();
const sectionActions = inject(workbenchSectionActionsKey, null);
const saving = ref(false);
const error = ref('');
const detailsOpen = ref(false);
const color = computed(() => (typeof props.data.color === 'string' && props.data.color) || DEFAULT_SECTION_COLOR);
const description = computed(() => typeof props.data.description === 'string' ? props.data.description : '');
const memberCount = computed(() => Array.isArray(props.data.node_keys) ? props.data.node_keys.length : 0);
const backgroundStyle = computed(() => ({
  '--workbench-section-color': color.value,
}));

function rename(event: Event) {
  const input = event.target as HTMLInputElement
  store.renameSection(props.id, input.value)
  input.value = store.nodeByKey(props.id)?.title || ''
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
    error.value = reason instanceof Error ? reason.message : tr('分区说明保存失败');
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
    error.value = reason instanceof Error ? reason.message : tr('分区删除失败');
  }
}

async function fitToContent() {
  error.value = '';
  try {
    await sectionActions?.fitToContent(props.id);
  }
  catch (reason) {
    error.value = reason instanceof Error ? reason.message : tr('分区适配内容失败');
  }
}
</script>

<template>
  <section class="workbench-section" :class="{ 'is-selected': selected, 'is-drop-target': data.drop_candidate === true }" :style="backgroundStyle" :aria-label="tr('{p0}，包含 {p1} 个节点', { p0: data.title || '画布分区', p1: memberCount })">
    <div v-if="selected" class="workbench-section__toolbar nodrag nowheel" role="toolbar" :aria-label="tr('分区操作')" @pointerdown.stop @click.stop>
      <button type="button" :aria-label="tr('取消编组')" :title="tr('删除分区（不会删除内部节点）')" @click="deleteSection">
        <Ungroup :size="17" aria-hidden="true" />
      </button>
      <WorkbenchColorPicker :color="color" :label="tr('修改分区颜色')" @change="store.setNodeColors([props.id], $event)" />
      <button type="button" :aria-label="tr('重新包裹内部节点')" :title="tr('重新包裹内部节点')" :disabled="memberCount === 0" @click="fitToContent">
        <Minimize2 :size="17" aria-hidden="true" />
      </button>
      <ElPopover trigger="click" placement="top" :width="260" :show-arrow="false" popper-class="workbench-color-popover"
        @show="detailsOpen = true" @hide="detailsOpen = false">
        <template #reference>
          <button type="button" :aria-label="tr('分区更多设置')" :title="tr('更多设置')" aria-haspopup="dialog" :aria-expanded="detailsOpen">
            <MoreVertical :size="17" aria-hidden="true" />
          </button>
        </template>
        <div class="workbench-group-editor" role="dialog" :aria-label="tr('分区更多设置')" @pointerdown.stop @click.stop>
          <label>{{ tr('组名') }}
            <input :value="String(data.title || '')" maxlength="100" @change="rename" @keydown.enter.prevent="($event.target as HTMLInputElement).blur()">
          </label>
          <label>{{ tr('分区文字说明') }}
            <textarea :value="description" maxlength="2000" rows="3" @input="updateDescription" @blur="saveDescription" />
          </label>
        </div>
      </ElPopover>
    </div>
    <header :title="tr('拖动节点进入分区可加入，拖出分区可移除；拖动标题栏可移动整个分区')">
      <Layers3 :size="16" aria-hidden="true" />
      <strong>{{ data.title || tr('画布分区') }}</strong>
      <span>{{ memberCount }} {{ tr('个节点') }}</span>
      <span v-if="selected" class="workbench-section__membership-hint">{{ tr('拖入加入 · 拖出移除') }}</span>
    </header>
    <p v-if="description" class="workbench-section__description-text">
      {{ description }}
    </p>
    <p v-if="error" class="workbench-section__error" role="alert">
      {{ error }}
    </p>
  </section>
</template>

<style scoped>
.workbench-section {
  background-color: color-mix(in srgb, var(--workbench-section-color) 14%, transparent);
  border-color: color-mix(in srgb, var(--workbench-section-color) 65%, var(--app-border));
}
.workbench-group-editor, .workbench-group-editor label { display: grid; gap: 6px; }
.workbench-group-editor { gap: 12px; color: var(--app-text-secondary); }
.workbench-group-editor :is(input, textarea) {
  width: 100%;
  box-sizing: border-box;
  padding: 6px 8px;
  font: inherit;
  color: var(--app-text);
  background: var(--app-surface);
  border: 1px solid var(--app-border-strong);
  border-radius: 6px;
}
.workbench-group-editor :focus-visible { outline: 2px solid var(--app-accent); outline-offset: 1px; }
</style>
