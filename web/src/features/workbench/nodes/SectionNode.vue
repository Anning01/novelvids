<script setup lang="ts">
import { tr } from '@/i18n'

import { ElPopover } from 'element-plus';
import type { NodeProps } from '@vue-flow/core';
import { Layers3, Minimize2, MoreHorizontal, Ungroup, X } from 'lucide-vue-next';
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
const detailsPopover = ref<InstanceType<typeof ElPopover>>();
const detailsTrigger = ref<HTMLButtonElement>();
function closeDetails() {
  detailsTrigger.value?.focus();
  detailsPopover.value?.hide();
}
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
    <header class="workbench-group-heading" :title="tr('拖动节点进入分区可加入，拖出分区可移除；拖动标题栏可移动整个分区')">
      <div class="workbench-group-caption">
        <Layers3 :size="15" aria-hidden="true" />
        <strong :title="String(data.title || '')">{{ data.title || tr('画布分区') }}</strong>
        <span class="workbench-group-count">{{ memberCount }} {{ tr('个节点') }}</span>
      </div>
      <div v-if="selected" class="workbench-section__toolbar nodrag nowheel" role="toolbar" :aria-label="tr('分区操作')" @pointerdown.stop @click.stop>
        <button type="button" :aria-label="tr('取消编组')" :title="tr('删除分区（不会删除内部节点）')" @click="deleteSection">
          <Ungroup :size="17" aria-hidden="true" />
        </button>
        <WorkbenchColorPicker :color="color" :label="tr('修改分区颜色')" @change="store.setNodeColors([props.id], $event)" />
        <button type="button" :aria-label="tr('重新包裹内部节点')" :title="tr('重新包裹内部节点')" :disabled="memberCount === 0" @click="fitToContent">
          <Minimize2 :size="17" aria-hidden="true" />
        </button>
        <ElPopover ref="detailsPopover" trigger="click" placement="top-start" :width="288" :offset="8"
          :popper-options="{ modifiers: [{ name: 'preventOverflow', options: { padding: 10 } }] }"
          :fallback-placements="['bottom-start', 'right-start', 'left-start']" :show-arrow="false" popper-class="workbench-group-popover"
          @show="detailsOpen = true" @hide="detailsOpen = false">
          <template #reference>
            <button ref="detailsTrigger" type="button" :aria-label="tr('分区更多设置')" :title="tr('更多设置')" aria-haspopup="dialog" :aria-expanded="detailsOpen">
              <MoreHorizontal :size="17" aria-hidden="true" />
            </button>
          </template>
          <div class="workbench-group-editor" role="dialog" :aria-label="tr('分组设置')" @pointerdown.stop @click.stop @keydown.esc.stop.prevent="closeDetails">
            <div class="workbench-group-editor__heading">
              <strong>{{ tr('分组设置') }}</strong>
              <button type="button" :aria-label="tr('关闭')" @click="closeDetails"><X :size="16" aria-hidden="true" /></button>
            </div>
            <label>{{ tr('组名') }}
              <input :value="String(data.title || '')" maxlength="100" @change="rename" @keydown.enter.prevent="($event.target as HTMLInputElement).blur()">
            </label>
            <label>{{ tr('说明') }}
              <textarea :value="description" :aria-label="tr('分区文字说明')" maxlength="2000" rows="3" @input="updateDescription" @blur="saveDescription" />
            </label>
          </div>
        </ElPopover>
      </div>
      <span v-if="description" class="workbench-group-summary" :title="description">{{ description }}</span>
      <span v-if="error" class="workbench-group-error" role="alert">{{ error }}</span>
    </header>
  </section>
</template>

<style scoped>
.workbench-section {
  background-color: color-mix(in srgb, var(--workbench-section-color) 14%, transparent);
  border-color: color-mix(in srgb, var(--workbench-section-color) 65%, var(--app-border));
}
.workbench-group-heading {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  width: max-content;
  max-width: 100%;
  color: var(--app-text);
  pointer-events: auto;
  user-select: none;
  cursor: grab;
}
.workbench-group-heading:active { cursor: grabbing; }
.workbench-group-caption, .workbench-section__toolbar { display: flex; align-items: center; }
.workbench-group-caption { min-width: 0; gap: 7px; font-size: 13px; line-height: 20px; }
.workbench-group-caption > svg, .workbench-group-count { flex: none; }
.workbench-group-caption > svg { color: color-mix(in srgb, var(--workbench-section-color) 65%, var(--app-text)); }
.workbench-group-caption strong, .workbench-group-summary, .workbench-group-error {
  overflow: hidden; white-space: nowrap; text-overflow: ellipsis;
}
.workbench-group-caption strong { max-width: min(16em, 24vw); font-weight: 650; }
.workbench-group-count, .workbench-group-summary { color: var(--app-text-secondary); font-size: 12px; }
.workbench-group-summary { max-width: 18em; padding-left: 8px; border-left: 1px solid var(--app-border-strong); }
.workbench-section__toolbar {
  flex: none; gap: 2px; padding: 3px; border: 1px solid var(--app-border-strong);
  border-radius: 10px; background: var(--app-surface); box-shadow: var(--app-shadow); cursor: default;
}
.workbench-section__toolbar :deep(button), .workbench-group-editor__heading button {
  display: inline-grid; place-items: center; width: 28px; height: 28px; padding: 0;
  border: 0; border-radius: 6px; color: var(--app-text-secondary); background: transparent; cursor: pointer;
}
.workbench-section__toolbar :deep(button:hover:not(:disabled)),
.workbench-section__toolbar :deep(button[aria-expanded="true"]),
.workbench-group-editor__heading button:hover { color: var(--app-text); background: var(--app-surface-hover); }
.workbench-section__toolbar :deep(button:disabled) { opacity: .45; cursor: default; }
.workbench-group-error { color: var(--creation-danger); font-size: 12px; }

:global(.el-popper.workbench-group-popover) {
  box-sizing: border-box; max-width: calc(100vw - 24px); padding: 0;
  border: 1px solid var(--app-border-strong); border-radius: 13px;
  color: var(--app-text); background: var(--app-surface); box-shadow: var(--app-shadow);
}
.workbench-group-editor { display: grid; gap: 14px; max-height: calc(100dvh - 24px); overflow-y: auto; padding: 14px 16px 16px; }
.workbench-group-editor__heading { display: flex; align-items: center; justify-content: space-between; }
.workbench-group-editor__heading strong { font-size: 14px; line-height: 20px; font-weight: 650; }
.workbench-group-editor label {
  display: grid; gap: 5px; color: var(--app-text-secondary); font-size: 12px; line-height: 18px;
}
.workbench-group-editor :is(input, textarea) {
  box-sizing: border-box; width: 100%; min-width: 0; padding: 8px 10px;
  border: 1px solid var(--app-border-strong); border-radius: 8px; color: var(--app-text);
  background: var(--app-surface-muted); font: inherit; font-size: 14px; line-height: 20px;
}
.workbench-group-editor textarea { resize: vertical; max-height: min(200px, 30vh); }
.workbench-group-editor :is(input, textarea):focus { border-color: var(--app-accent); background: var(--app-surface); }
.workbench-group-editor :focus-visible, .workbench-section__toolbar :deep(button:focus-visible) {
  outline: 2px solid var(--app-accent); outline-offset: 2px;
}
</style>
