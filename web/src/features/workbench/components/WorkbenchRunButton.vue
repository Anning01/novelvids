<script setup lang="ts">
import { LoaderCircle, Play } from 'lucide-vue-next';

withDefaults(defineProps<{
  label: string;
  ariaLabel?: string;
  busy?: boolean;
  busyLabel?: string;
  progress?: number | null;
  disabled?: boolean;
}>(), {
  ariaLabel: '',
  busy: false,
  busyLabel: '处理中…',
  progress: null,
  disabled: false,
});

defineEmits<{
  click: [event: MouseEvent];
}>();
</script>

<template>
  <button
    type="button"
    class="workbench-run-button nodrag nopan"
    :class="{ 'is-busy': busy }"
    :disabled="disabled || busy"
    :aria-label="ariaLabel || label"
    :aria-busy="busy"
    @click="$emit('click', $event)"
  >
    <span class="workbench-run-button__content">
      <LoaderCircle v-if="busy" class="workbench-run-button__spinner" :size="15" aria-hidden="true" />
      <Play v-else :size="14" :stroke-width="2" aria-hidden="true" />
      <span>{{ busy ? busyLabel : label }}</span>
    </span>
    <span v-if="busy && progress !== null" class="workbench-run-button__progress" aria-hidden="true">
      <i :style="{ width: `${Math.min(100, Math.max(0, progress))}%` }" />
    </span>
  </button>
</template>
