<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { Check, Palette, X } from 'lucide-vue-next'
import { ElPopover } from 'element-plus'
import { tr } from '@/i18n'
import { WORKBENCH_NODE_MARKER_COLORS } from '../graph/nodeAppearance'

defineProps<{ color: string; label: string; disabled?: boolean }>()
const emit = defineEmits<{ change: [color: string] }>()
const popover = ref<InstanceType<typeof ElPopover>>()
const trigger = ref<HTMLButtonElement>()
const options = ref<HTMLElement>()
const open = ref(false)

function focusColor() {
  void nextTick(() => {
    const target = options.value?.querySelector<HTMLButtonElement>('button[aria-pressed="true"]')
      ?? options.value?.querySelector('button')
    target?.focus()
  })
}
function close() {
  popover.value?.hide()
  trigger.value?.focus()
}
function choose(color: string) {
  emit('change', color)
  close()
}
</script>

<template>
  <ElPopover ref="popover" trigger="click" placement="top" :width="210" :show-arrow="false"
    :disabled="disabled" popper-class="workbench-color-popover" @show="open = true" @after-enter="focusColor" @hide="open = false">
    <template #reference>
      <button ref="trigger" type="button" class="workbench-color-trigger nodrag" :aria-label="label" :title="label"
        :disabled="disabled" aria-haspopup="dialog" :aria-expanded="open" @pointerdown.stop @keydown.space.stop>
        <Palette :size="17" aria-hidden="true" :style="color ? { color } : undefined" />
      </button>
    </template>
    <div ref="options" class="workbench-color-options" role="dialog" :aria-label="label" @pointerdown.stop @click.stop @keydown.stop @keydown.esc.prevent="close">
      <button v-for="swatch in WORKBENCH_NODE_MARKER_COLORS" :key="swatch" type="button"
        :style="{ backgroundColor: swatch }" :aria-pressed="color === swatch"
        :aria-label="tr('使用背景颜色 {p0}', { p0: swatch })" @click="choose(swatch)">
        <Check v-if="color === swatch" :size="13" />
      </button>
      <label>{{ tr('自定义背景颜色') }}
        <input type="color" :value="color || WORKBENCH_NODE_MARKER_COLORS[0]" :aria-label="tr('自定义背景颜色')" @change="choose(($event.target as HTMLInputElement).value)">
      </label>
      <button class="clear-color" type="button" :aria-label="tr('清除节点背景颜色')" :title="tr('清除节点背景颜色')" @click="choose('')"><X :size="15" /></button>
    </div>
  </ElPopover>
</template>

<style>
.el-popper.workbench-color-popover { color: var(--app-text); border-color: var(--app-border-strong); background: var(--app-surface); box-shadow: var(--app-shadow); }
.workbench-color-options { display: grid; grid-template-columns: repeat(6, 1fr); gap: 6px; }
.workbench-color-options button { display: grid; place-items: center; min-height: 25px; padding: 0; border: 1px solid var(--app-border-strong); border-radius: 6px; cursor: pointer; color: #191919; }
.workbench-color-options label { display: flex; align-items: center; justify-content: space-between; grid-column: span 5; color: var(--app-text); }
.workbench-color-options input { width: 28px; cursor: pointer; }
.workbench-color-options .clear-color { color: var(--app-text); background: var(--app-surface-muted); }
.workbench-color-options :is(input, button):focus-visible { outline: 2px solid var(--app-accent); outline-offset: 2px; }
</style>
