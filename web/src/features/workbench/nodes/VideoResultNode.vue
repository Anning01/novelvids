<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { computed } from 'vue'
import { RefreshCw } from 'lucide-vue-next'
import { statusLabel } from '@/api'
import type { Video } from '@/types'
import { TaskStatusEnum } from '@/types'
import { useWorkbenchStore } from '../store/workbenchStore'
import WorkbenchMediaResultState from '../components/WorkbenchMediaResultState.vue'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
const props = defineProps<NodeProps>(); const store = useWorkbenchStore(); const video = computed(() => props.data.video as Video); const processing = computed(() => ![TaskStatusEnum.COMPLETED, TaskStatusEnum.FAILED, TaskStatusEnum.CANCELLED].includes(video.value.status))
const failed = computed(() => [TaskStatusEnum.FAILED, TaskStatusEnum.CANCELLED].includes(video.value.status))
const failureMessage = computed(() => {
  const metadata = video.value.metadata || {}
  for (const value of [metadata.error_message, metadata.error, metadata.message, metadata.detail]) if (typeof value === 'string' && value.trim()) return value
  return video.value.status === TaskStatusEnum.CANCELLED ? '生成任务已取消' : '视频生成失败'
})
</script>
<template><WorkbenchNodeFrame v-bind="props" :data="{ ...data, kind: 'video_result', title: `视频结果 · #${video.id}`, status: statusLabel(video.status) }"><div class="workbench-node-summary"><video v-if="video.url" class="workbench-node-summary__media" :src="video.url" controls preload="metadata" /><WorkbenchMediaResultState v-else :running="processing" :failed="failed" :error="failureMessage" :progress="video.progress || 0" running-label="正在生成镜头视频" failure-label="视频生成失败" empty-label="视频结果尚未就绪" /><AppButton v-if="processing" class="workbench-inline-action" type="button" @click="store.refreshVideo(video.id)"><RefreshCw :size="14" />刷新状态</AppButton></div></WorkbenchNodeFrame></template>
