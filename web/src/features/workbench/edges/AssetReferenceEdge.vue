<script setup lang="ts">
import type { EdgeProps } from '@vue-flow/core';
import { BaseEdge, getBezierPath } from '@vue-flow/core';
import { computed } from 'vue';

const props = defineProps<EdgeProps>();
const path = computed(() => getBezierPath(props)[0]);
</script>

<template>
  <BaseEdge :id="id" :path="path" class="workbench-edge workbench-edge--asset" :aria-label="label || '资产引用连线'" />
</template>
