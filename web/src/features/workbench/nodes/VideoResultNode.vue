<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { computed } from 'vue'
import { LoaderCircle, RefreshCw } from 'lucide-vue-next'
import { statusLabel } from '@/api'
import type { Video } from '@/types'
import { TaskStatusEnum } from '@/types'
import { useWorkbenchStore } from '../store/workbenchStore'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
const props = defineProps<NodeProps>(); const store = useWorkbenchStore(); const video = computed(() => props.data.video as Video); const processing = computed(() => ![TaskStatusEnum.COMPLETED, TaskStatusEnum.FAILED, TaskStatusEnum.CANCELLED].includes(video.value.status))
</script>
<template><WorkbenchNodeFrame v-bind="props" :data="{ ...data, kind: 'video_result', title: `视频结果 · #${video.id}`, status: statusLabel(video.status) }"><div class="workbench-node-summary"><video v-if="video.url" class="workbench-node-summary__media" :src="video.url" controls preload="metadata" /><div v-else class="workbench-media-empty"><LoaderCircle v-if="processing" class="workbench-node-context__loading-icon" :size="24" />{{ processing ? '视频生成中…' : String(video.metadata?.error || '生成失败') }}</div><AppButton v-if="processing" class="workbench-inline-action" type="button" @click="store.refreshVideo(video.id)"><RefreshCw :size="14" />刷新状态</AppButton></div></WorkbenchNodeFrame></template>
