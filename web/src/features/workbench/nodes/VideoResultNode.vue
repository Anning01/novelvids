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
const failureMessage = computed(() => {
  const metadata = video.value.metadata || {}
  for (const value of [metadata.error_message, metadata.error, metadata.message, metadata.detail]) if (typeof value === 'string' && value.trim()) return value
  return video.value.status === TaskStatusEnum.CANCELLED ? '生成任务已取消' : '视频生成失败'
})
</script>
<template><WorkbenchNodeFrame v-bind="props" :data="{ ...data, kind: 'video_result', title: `视频结果 · #${video.id}`, status: statusLabel(video.status) }"><div class="workbench-node-summary"><video v-if="video.url" class="workbench-node-summary__media" :src="video.url" controls preload="metadata" /><div v-else class="workbench-media-empty" :class="{ 'is-error': !processing }" :role="processing ? 'status' : 'alert'"><LoaderCircle v-if="processing" class="workbench-node-context__loading-icon" :size="24" /><strong>{{ processing ? '视频生成中…' : '视频生成失败' }}</strong><span v-if="!processing">{{ failureMessage }}</span></div><AppButton v-if="processing" class="workbench-inline-action" type="button" @click="store.refreshVideo(video.id)"><RefreshCw :size="14" />刷新状态</AppButton></div></WorkbenchNodeFrame></template>
