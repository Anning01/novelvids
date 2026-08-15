<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { Download, LoaderCircle, RefreshCw } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { statusLabel } from '@/api'
import { downloadFile } from '@/shared/downloadFile'
import type { Video } from '@/types'
import { TaskStatusEnum } from '@/types'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
import WorkbenchVideoMedia from '../components/WorkbenchVideoMedia.vue'
import { videoAspectRatio, videoCoverUrl, videoDownloadFilename, videoPixelSize, videoResolution } from '../graph/videoMedia'
import { useWorkbenchStore } from '../store/workbenchStore'

const props = defineProps<NodeProps>()
const store = useWorkbenchStore()
const video = computed(() => props.data.video as Video)
const processing = computed(() => ![TaskStatusEnum.COMPLETED, TaskStatusEnum.FAILED, TaskStatusEnum.CANCELLED].includes(video.value.status))
const failed = computed(() => [TaskStatusEnum.FAILED, TaskStatusEnum.CANCELLED].includes(video.value.status))
const failureMessage = computed(() => {
  const metadata = video.value.metadata || {}
  for (const value of [metadata.error_message, metadata.error, metadata.message, metadata.detail]) {
    if (typeof value === 'string' && value.trim()) return value
  }
  return video.value.status === TaskStatusEnum.CANCELLED ? '生成任务已取消' : '视频生成失败'
})
const title = computed(() => `视频结果 · #${video.value.id}`)
const filename = computed(() => videoDownloadFilename(video.value, title.value))
const downloading = ref(false)
const downloadError = ref('')
const measuredVideoSize = ref<{ width: number; height: number } | null>(null)
const displayedRatio = computed(() => measuredVideoSize.value
  ? `${measuredVideoSize.value.width}:${measuredVideoSize.value.height}`
  : videoAspectRatio(video.value))
const mediaSizeLabel = computed(() => {
  const size = measuredVideoSize.value || videoPixelSize(video.value)
  const pixelSize = size ? `${Math.round(size.width)} × ${Math.round(size.height)}` : ''
  return [videoResolution(video.value), videoAspectRatio(video.value), pixelSize].filter(Boolean).join(' · ')
})

async function downloadVideo() {
  if (!video.value.url || downloading.value) return
  downloading.value = true
  downloadError.value = ''
  try {
    await downloadFile(video.value.url, filename.value)
  } catch (error) {
    downloadError.value = error instanceof Error ? error.message : '视频下载失败'
  } finally {
    downloading.value = false
  }
}
</script>

<template>
  <WorkbenchNodeFrame
    v-bind="props"
    :data="{ ...data, kind: 'video_result', title, status: statusLabel(video.status), body_flush: true, floating_header: true, borderless_media: true }"
  >
    <template v-if="mediaSizeLabel" #meta>
      <span class="workbench-node-frame__media-size">{{ mediaSizeLabel }}</span>
    </template>
    <template #toolbar-actions>
      <button
        type="button"
        :disabled="!video.url || downloading"
        :aria-label="`下载视频，保存为 ${filename}`"
        :title="`下载 · ${filename}`"
        @click="downloadVideo"
      >
        <LoaderCircle v-if="downloading" class="workbench-node-context__loading-icon" :size="16" aria-hidden="true" />
        <Download v-else :size="16" aria-hidden="true" />
      </button>
    </template>
    <div class="workbench-node-content workbench-media-node">
      <WorkbenchVideoMedia
        :src="video.url"
        :poster="videoCoverUrl(video)"
        :title="title"
        :ratio="displayedRatio"
        :running="processing"
        :failed="failed"
        :error="failureMessage"
        :progress="video.progress || 0"
        @metadata="measuredVideoSize = $event"
      />
      <AppButton v-if="processing" class="workbench-inline-action" type="button" @click="store.refreshVideo(video.id)">
        <RefreshCw :size="14" aria-hidden="true" />刷新状态
      </AppButton>
      <p v-if="downloadError" role="alert">{{ downloadError }}</p>
    </div>
  </WorkbenchNodeFrame>
</template>
