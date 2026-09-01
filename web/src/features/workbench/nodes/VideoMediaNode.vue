<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { Upload, Video } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { notice } from '@/shared/notice'
import DeferredVideoPlayer from '@/components/DeferredVideoPlayer.vue'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
import { useWorkbenchStore } from '../store/workbenchStore'

const props = defineProps<NodeProps>()
const store = useWorkbenchStore()
const uploading = ref(false)
const url = computed(() => typeof props.data.url === 'string' ? props.data.url : '')
const title = computed(() => String(props.data.title || props.data.originalFilename || '上传视频'))
const duration = computed(() => {
  const seconds = Number(props.data.durationSeconds)
  return Number.isFinite(seconds) && seconds > 0 ? `${seconds.toFixed(1).replace(/\.0$/, '')} 秒` : ''
})

async function replace(event: Event) {
  const input = event.currentTarget as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  uploading.value = true
  try {
    await store.replaceUploadedMedia(props.id, file)
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '视频上传失败')
  } finally {
    uploading.value = false
  }
}

function captureMetadata(event: Event) {
  const video = event.currentTarget as HTMLVideoElement
  store.updateUploadedMediaMetadata(props.id, {
    width: video.videoWidth,
    height: video.videoHeight,
    durationSeconds: video.duration,
  })
}
</script>

<template>
  <WorkbenchNodeFrame v-bind="props" :data="{ ...data, kind: 'video_media', title, status: uploading ? '上传中' : 'ready' }">
    <div class="workbench-uploaded-media-node workbench-uploaded-video-node">
      <span class="workbench-uploaded-media-node__type"><Video :size="14" aria-hidden="true" />视频</span>
      <DeferredVideoPlayer v-if="url" :src="url" :title="title" @loadedmetadata="captureMetadata" />
      <div v-else class="workbench-media-placeholder">视频不可用</div>
      <small v-if="duration">{{ duration }}</small>
      <label class="workbench-uploaded-media-node__replace" :class="{ 'is-disabled': uploading }">
        <Upload :size="14" aria-hidden="true" />{{ uploading ? '上传中…' : '重新上传' }}
        <input type="file" accept="video/mp4,video/webm,video/quicktime" aria-label="上传资产视频" :disabled="uploading" @change="replace">
      </label>
    </div>
  </WorkbenchNodeFrame>
</template>
