<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { Image, Upload } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { notice } from '@/shared/notice'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
import { useWorkbenchStore } from '../store/workbenchStore'

const props = defineProps<NodeProps>()
const store = useWorkbenchStore()
const uploading = ref(false)
const url = computed(() => typeof props.data.url === 'string' ? props.data.url : '')
const title = computed(() => String(props.data.title || props.data.originalFilename || '上传图片'))
const dimensions = computed(() => {
  const width = Number(props.data.width)
  const height = Number(props.data.height)
  return width > 0 && height > 0 ? `${width} × ${height}` : ''
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
    notice.error(error instanceof Error ? error.message : '图片上传失败')
  } finally {
    uploading.value = false
  }
}

function captureDimensions(event: Event) {
  const image = event.currentTarget as HTMLImageElement
  store.updateUploadedMediaMetadata(props.id, { width: image.naturalWidth, height: image.naturalHeight })
}
</script>

<template>
  <WorkbenchNodeFrame v-bind="props" :data="{ ...data, kind: 'image_media', title, status: uploading ? '上传中' : 'ready' }">
    <div class="workbench-uploaded-media-node workbench-uploaded-image-node">
      <span class="workbench-uploaded-media-node__type"><Image :size="14" aria-hidden="true" />图片</span>
      <img v-if="url" :src="url" :alt="`${title}预览`" @load="captureDimensions">
      <div v-else class="workbench-media-placeholder">图片不可用</div>
      <small v-if="dimensions">{{ dimensions }}</small>
      <label class="workbench-uploaded-media-node__replace" :class="{ 'is-disabled': uploading }">
        <Upload :size="14" aria-hidden="true" />{{ uploading ? '上传中…' : '重新上传' }}
        <input type="file" accept="image/png,image/jpeg,image/webp" aria-label="上传资产图片" :disabled="uploading" @change="replace">
      </label>
    </div>
  </WorkbenchNodeFrame>
</template>
