<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { Upload, Volume2 } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { notice } from '@/shared/notice'
import WorkbenchAudioMedia from '../components/WorkbenchAudioMedia.vue'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
import { useWorkbenchStore } from '../store/workbenchStore'

const props = defineProps<NodeProps>()
const store = useWorkbenchStore()
const uploading = ref(false)
const url = computed(() => typeof props.data.url === 'string' ? props.data.url : '')
const title = computed(() => String(props.data.title || props.data.originalFilename || '上传音频'))
const durationSeconds = computed(() => Number(props.data.durationSeconds) || 0)

async function replace(event: Event) {
  const input = event.currentTarget as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  uploading.value = true
  try {
    await store.replaceUploadedMedia(props.id, file)
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '音频上传失败')
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <WorkbenchNodeFrame v-bind="props" :data="{ ...data, kind: 'audio_media', title, status: uploading ? '上传中' : 'ready' }">
    <div class="workbench-uploaded-media-node workbench-uploaded-audio-node">
      <span class="workbench-uploaded-media-node__type"><Volume2 :size="14" aria-hidden="true" />音频</span>
      <WorkbenchAudioMedia v-if="url" :src="url" :title="title" source-label="上传音频" :duration-seconds="durationSeconds" />
      <div v-else class="workbench-media-placeholder">音频不可用</div>
      <label class="workbench-uploaded-media-node__replace" :class="{ 'is-disabled': uploading }">
        <Upload :size="14" aria-hidden="true" />{{ uploading ? '上传中…' : '重新上传' }}
        <input type="file" accept="audio/mpeg,audio/wav,audio/mp4,audio/webm" aria-label="上传资产音频" :disabled="uploading" @change="replace">
      </label>
    </div>
  </WorkbenchNodeFrame>
</template>
