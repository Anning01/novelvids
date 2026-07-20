<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { computed } from 'vue'
import type { Chapter } from '@/types'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
const props = defineProps<NodeProps>()
const chapter = computed(() => props.data.chapter as Chapter)
</script>
<template><WorkbenchNodeFrame v-bind="props" :data="{ ...data, kind: 'chapter', title: props.label || `第 ${chapter.number} 章` }"><div class="workbench-node-content"><p class="workbench-node-summary__prompt">{{ chapter.content || '本章暂无正文' }}</p><small>{{ (chapter.content || '').length.toLocaleString() }} 字 · 章节内容源</small></div></WorkbenchNodeFrame></template>
