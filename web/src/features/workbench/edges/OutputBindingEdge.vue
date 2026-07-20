<script setup lang="ts">
import type { EdgeProps } from '@vue-flow/core';
import { BaseEdge, getBezierPath } from '@vue-flow/core';
import { computed } from 'vue';

const props = defineProps<EdgeProps>();
const path = computed(() => getBezierPath(props)[0]);
const edgeClass = computed(() => props.sourceHandleId === 'watermark-output'
  ? 'workbench-edge workbench-edge--watermark'
  : 'workbench-edge workbench-edge--output');
</script>

<template>
  <BaseEdge :id="id" :path="path" :class="edgeClass" :aria-label="label || '输出绑定连线'" />
</template>
