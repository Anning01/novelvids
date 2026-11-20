<script setup lang="ts">
import { tr } from '@/i18n'

import type { EdgeProps } from '@vue-flow/core';
import { BaseEdge } from '@vue-flow/core';
import { useWorkbenchWire } from './useWorkbenchWire';

const props = defineProps<EdgeProps>();
const path = useWorkbenchWire(props);
</script>

<template>
  <BaseEdge :id="id" :path="path" class="workbench-edge workbench-edge--asset" :aria-label="label || tr('资产引用连线')" />
</template>
