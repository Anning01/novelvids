<script setup lang="ts">
import { tr } from '@/i18n'

import type { NodeProps } from '@vue-flow/core'
import { Upload, Video } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { notice } from '@/shared/notice'
import SaveVideoToLibrary from '@/features/resource-library/SaveVideoToLibrary.vue'
import { libraryApi } from '@/features/resource-library/api'
import { mediaUrl } from '@/api'
import DeferredVideoPlayer from '@/components/DeferredVideoPlayer.vue'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
import { useWorkbenchStore } from '../store/workbenchStore'

const props = defineProps<NodeProps>()
const store = useWorkbenchStore()
const uploading = ref(false)
const libraryError = ref('')
const libraryUrl = ref('')
let libraryRequest = 0
watch(() => props.data.library_resource_id, async value => {
  const request = ++libraryRequest
  libraryError.value = ''; libraryUrl.value = ''
  if (!value) return
  try { const response = await libraryApi.get(Number(value)); if (request === libraryRequest) libraryUrl.value = response.data.url }
  catch { if (request === libraryRequest) libraryError.value = tr('资源视频已删除或不可用，请移除节点或重新上传') }
}, { immediate: true })
const url = computed(() => typeof props.data.url === 'string' ? props.data.url : '')
const title = computed(() => String(props.data.title || props.data.originalFilename || tr('上传视频')))
const duration = computed(() => {
  const seconds = Number(props.data.durationSeconds)
  return Number.isFinite(seconds) && seconds > 0 ? tr('{p0} 秒', { p0: seconds.toFixed(1).replace(/\.0$/, '') }) : ''
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
    notice.error(error instanceof Error ? error.message : tr('视频上传失败'))
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
  <WorkbenchNodeFrame v-bind="props" :data="{ ...data, kind: 'video_media', title, status: uploading ? tr('上传中') : 'ready' }">
    <div class="workbench-uploaded-media-node workbench-uploaded-video-node">
      <span class="workbench-uploaded-media-node__type"><Video :size="14" aria-hidden="true" />{{ tr('视频') }}</span>
      <DeferredVideoPlayer v-if="url && !libraryError" :src="mediaUrl(libraryUrl || url)" :title="title" @loadedmetadata="captureMetadata" />
      <div v-else class="workbench-media-placeholder">{{ libraryError || tr('视频不可用') }}</div>
      <SaveVideoToLibrary v-if="data.upload_source_id" :source="{ source: 'upload', source_id: Number(data.upload_source_id), name: title }" />
      <small v-if="duration">{{ duration }}</small>
      <label class="workbench-uploaded-media-node__replace" :class="{ 'is-disabled': uploading }">
        <Upload :size="14" aria-hidden="true" />{{ uploading ? tr('上传中…') : tr('重新上传') }}
        <input type="file" accept="video/mp4,video/webm,video/quicktime" :aria-label="tr('上传资产视频')" :disabled="uploading" @change="replace">
      </label>
    </div>
  </WorkbenchNodeFrame>
</template>
