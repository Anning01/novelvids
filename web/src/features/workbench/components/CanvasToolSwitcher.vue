<script setup lang="ts">
import { tr } from '@/i18n'

import { Hand, MousePointer2 } from 'lucide-vue-next';

defineProps<{ modelValue: 'select' | 'pan' }>();
const emit = defineEmits<{ 'update:modelValue': [value: 'select' | 'pan'] }>();
</script>

<template>
  <div class="workbench-canvas-tools" role="toolbar" :aria-label="tr('画布操作模式')">
    <button
      type="button"
      class="workbench-canvas-tools__button"
      :class="{ 'is-active': modelValue === 'select' }"
      :aria-pressed="modelValue === 'select'"
      :aria-label="tr('选择工具')"
      :title="tr('选择工具')"
      @pointerdown.stop
      @click.stop="emit('update:modelValue', 'select')"
    >
      <MousePointer2 :size="20" aria-hidden="true" />
    </button>
    <button
      type="button"
      class="workbench-canvas-tools__button"
      :class="{ 'is-active': modelValue === 'pan' }"
      :aria-pressed="modelValue === 'pan'"
      :aria-label="tr('拖动画布工具')"
      :title="tr('拖动画布工具')"
      @pointerdown.stop
      @click.stop="emit('update:modelValue', 'pan')"
    >
      <Hand :size="20" aria-hidden="true" />
    </button>
  </div>
</template>
