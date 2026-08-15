<script setup lang="ts">
import type { CSSProperties } from 'vue';
import type { WorkbenchPromptAction, WorkbenchPromptActionControl } from '../prompt/promptActionRegistry';
import type { WorkbenchPromptEditor } from '../types/workbenchTypes';
import type { MaterialMention, MaterialMentionOption } from './materialMentionTypes';
import { LoaderCircle, Maximize2, Minimize2, Play, X } from 'lucide-vue-next';
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, unref, watch } from 'vue';
import { workbenchPromptActionRegistryKey } from '../prompt/promptActionRegistry';
import MaterialMentionInput from './MaterialMentionInput.vue';
import PromptReferenceImageStrip from './PromptReferenceImageStrip.vue';

const props = defineProps<{
  open: boolean;
  nodeKey: string;
  config: WorkbenchPromptEditor;
  modelValue: string;
  materials: MaterialMentionOption[];
  mentions: MaterialMention[];
}>();
const emit = defineEmits<{
  'update:modelValue': [value: string];
  'add': [material: MaterialMentionOption, prompt: string];
  'close': [];
  'focusout': [event: FocusEvent];
  'focusReference': [nodeKey: string];
  'removeReference': [edgeKey: string];
}>();

const panel = ref<HTMLElement | null>(null);
const panelStyle = ref<CSSProperties>({ visibility: 'hidden' });
const expanded = ref(false);
const actionRegistry = inject(workbenchPromptActionRegistryKey, null);
let animationFrame = 0;

const promptLength = computed(() => Array.from(props.modelValue.trim()).length);
const promptActions = computed(() => actionRegistry?.actions.get(props.nodeKey) ?? []);
const promptControls = computed(() => promptActions.value.flatMap((action) => {
  const controls = [...(action.control ? [action.control] : []), ...(action.controls ?? [])];
  return controls.filter(control => !control.visible || unref(control.visible));
}));

function actionBusy(action: WorkbenchPromptAction) {
  return unref(action.busy);
}

function actionEnabled(action: WorkbenchPromptAction) {
  return unref(action.enabled);
}

function actionProgress(action: WorkbenchPromptAction) {
  return action.progress ? unref(action.progress) : null;
}

function actionCost(action: WorkbenchPromptAction) {
  return action.cost ? unref(action.cost) : 0;
}

function controlProps(control: WorkbenchPromptActionControl) {
  return control.props ? unref(control.props) : {};
}

function controlModelValue(control: WorkbenchPromptActionControl) {
  return unref(control.modelValue);
}

function addMaterial(material: MaterialMentionOption, prompt: string) {
  emit('add', material, prompt);
}

function anchorElement() {
  return [...document.querySelectorAll<HTMLElement>('.vue-flow__node')]
    .find(element => element.dataset.id === props.nodeKey) ?? null;
}

function updatePosition() {
  if (!props.open)
    return;
  const currentPanel = panel.value;
  if (!currentPanel)
    return;
  const viewportPadding = expanded.value ? 24 : 12;
  if (expanded.value) {
    panelStyle.value = {
      top: '8vh',
      left: '50%',
      width: `${Math.min(1540, window.innerWidth - viewportPadding * 2)}px`,
      height: '84vh',
      maxHeight: '84vh',
      bottom: 'auto',
      transform: 'translateX(-50%)',
      visibility: 'visible',
    };
    return;
  }
  const anchor = anchorElement();
  if (!anchor) {
    panelStyle.value = {
      left: '50%',
      bottom: '18px',
      transform: 'translateX(-50%)',
      visibility: 'visible',
    };
    return;
  }
  const anchorRect = anchor.getBoundingClientRect();
  const gap = 6;
  const width = Math.min(960, Math.max(360, window.innerWidth * 0.4), window.innerWidth - viewportPadding * 2);
  const left = anchorRect.left + anchorRect.width / 2 - width / 2;
  const top = anchorRect.bottom + gap;
  const availableHeight = Math.max(160, window.innerHeight - top - viewportPadding);
  const height = Math.min(availableHeight, Math.max(320, window.innerHeight * 0.4));
  panelStyle.value = {
    top: `${top}px`,
    left: `${left}px`,
    width: `${width}px`,
    height: `${height}px`,
    maxHeight: `${height}px`,
    bottom: 'auto',
    transform: 'none',
    visibility: 'visible',
  };
}

function stopPositioning() {
  if (!animationFrame)
    return;
  cancelAnimationFrame(animationFrame);
  animationFrame = 0;
}

function startPositioning() {
  stopPositioning();
  const position = () => {
    updatePosition();
    animationFrame = requestAnimationFrame(position);
  };
  position();
}

watch(() => props.open, async (open) => {
  if (!open) {
    stopPositioning();
    expanded.value = false;
    return;
  }
  panelStyle.value = { visibility: 'hidden' };
  await nextTick();
  startPositioning();
}, { immediate: true });

watch(expanded, async () => {
  await nextTick();
  updatePosition();
});

onMounted(() => window.addEventListener('resize', updatePosition));
onBeforeUnmount(() => {
  stopPositioning();
  window.removeEventListener('resize', updatePosition);
});
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open && expanded"
      class="workbench-prompt-focus-backdrop"
      aria-hidden="true"
      @pointerdown="expanded = false"
    />
    <section
      v-if="open"
      ref="panel"
      class="viral-workbench-surface-theme workbench-prompt-panel nodrag nowheel"
      :class="{ 'is-expanded': expanded }"
      :style="panelStyle"
      role="dialog"
      :aria-modal="expanded"
      :aria-label="`${config.label}编辑器`"
      @pointerdown.stop
      @click.stop
      @wheel.stop
      @focusout="emit('focusout', $event)"
    >
      <div class="workbench-prompt-panel__actions">
        <button
          type="button"
          :aria-label="expanded ? '退出 Prompt 专注模式' : '进入 Prompt 专注模式'"
          :title="expanded ? '退出专注模式' : '进入专注模式'"
          :aria-pressed="expanded"
          @click="expanded = !expanded"
        >
          <Minimize2 v-if="expanded" :size="18" aria-hidden="true" />
          <Maximize2 v-else :size="18" aria-hidden="true" />
        </button>
        <button type="button" aria-label="关闭 Prompt 编辑器" title="关闭" @click="emit('close')">
          <X :size="18" aria-hidden="true" />
        </button>
      </div>

      <PromptReferenceImageStrip
        :mentions="mentions"
        @focus="emit('focusReference', $event)"
        @remove="emit('removeReference', $event)"
      />

      <MaterialMentionInput
        :model-value="modelValue"
        :materials="materials"
        :mentions="mentions"
        :label="config.label"
        :placeholder="config.placeholder"
        :image-limit="config.referenceLimits.image"
        :video-limit="config.referenceLimits.video"
        :audio-limit="config.referenceLimits.audio"
        :show-hint="false"
        :show-reference-counts="false"
        @update:model-value="emit('update:modelValue', $event)"
        @add="addMaterial"
      />

      <footer class="workbench-prompt-panel__footer">
        <div class="workbench-prompt-panel__footer-start">
          <span class="workbench-prompt-panel__count">{{ promptLength }} 字</span>
          <component
            :is="control.component"
            v-for="control in promptControls"
            :key="control.id"
            v-bind="controlProps(control)"
            :model-value="controlModelValue(control)"
            v-on="control.events ?? {}"
            @update:model-value="control.updateModelValue"
          />
        </div>
        <div v-if="promptActions.length" class="workbench-prompt-panel__footer-actions" aria-label="Prompt 操作">
          <button
            v-for="action in promptActions"
            :key="action.id"
            type="button"
            class="workbench-prompt-panel__primary-action"
            :class="{ 'is-busy': actionBusy(action) }"
            :disabled="!actionEnabled(action) || actionBusy(action)"
            :aria-label="action.label"
            :aria-busy="actionBusy(action)"
            :title="action.label"
            @click="action.run"
          >
            <LoaderCircle v-if="actionBusy(action)" class="workbench-prompt-panel__action-spinner" :size="15" aria-hidden="true" />
            <Play v-else :size="14" aria-hidden="true" />
            <span>{{ actionBusy(action) ? (action.busyLabel || '处理中') : action.label }}</span>
            <span v-if="!actionBusy(action) && actionCost(action) > 0" class="workbench-prompt-panel__action-cost">约 ¥{{ actionCost(action).toFixed(2) }}</span>
            <i v-if="actionProgress(action) !== null" aria-hidden="true">
              <b :style="{ width: `${actionProgress(action)}%` }" />
            </i>
          </button>
        </div>
      </footer>
    </section>
  </Teleport>
</template>
