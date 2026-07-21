<script setup lang="ts">
import { Hand, MousePointer2 } from 'lucide-vue-next';

defineProps<{ modelValue: 'select' | 'pan' }>();
const emit = defineEmits<{ 'update:modelValue': [value: 'select' | 'pan'] }>();
</script>

<template>
  <div class="workbench-canvas-tools" role="toolbar" aria-label="画布操作模式">
    <AppButton
      type="button"
      class="workbench-canvas-tools__button"
      :class="{ 'is-active': modelValue === 'select' }"
      :aria-pressed="modelValue === 'select'"
      aria-label="选择工具"
      title="选择工具"
      @pointerdown.stop
      @click.stop="emit('update:modelValue', 'select')"
    >
      <MousePointer2 :size="20" aria-hidden="true" />
    </AppButton>
    <AppButton
      type="button"
      class="workbench-canvas-tools__button"
      :class="{ 'is-active': modelValue === 'pan' }"
      :aria-pressed="modelValue === 'pan'"
      aria-label="拖动画布工具"
      title="拖动画布工具"
      @pointerdown.stop
      @click.stop="emit('update:modelValue', 'pan')"
    >
      <Hand :size="20" aria-hidden="true" />
    </AppButton>
  </div>
</template>
