<script setup lang="ts">
import { tr } from '@/i18n'

import type { EdgeProps } from '@vue-flow/core';
import { BaseEdge } from '@vue-flow/core';
import { computed } from 'vue';
import { useWorkbenchWire } from './useWorkbenchWire';

const props = defineProps<EdgeProps>();
const path = useWorkbenchWire(props);
const edgeClass = computed(() => props.sourceHandleId === 'watermark-output'
  ? 'workbench-edge workbench-edge--watermark'
  : 'workbench-edge workbench-edge--output');
</script>

<template>
  <BaseEdge :id="id" :path="path" :class="edgeClass" :aria-label="label || tr('输出绑定连线')" />
</template>
