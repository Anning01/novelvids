<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { Image, Pencil, Upload } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { notice } from '@/shared/notice'
import ImageAnnotationDialog from '../components/ImageAnnotationDialog.vue'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
import { useWorkbenchStore } from '../store/workbenchStore'
import type { ImageAnnotation } from '../types/workbenchTypes'

const props = defineProps<NodeProps>()
const store = useWorkbenchStore()
const uploading = ref(false)
const annotationOpen = ref(false)
const url = computed(() => typeof props.data.url === 'string' ? props.data.url : '')
const title = computed(() => String(props.data.title || props.data.originalFilename || '上传图片'))
const annotations = computed(() => Array.isArray(props.data.annotations) ? props.data.annotations as ImageAnnotation[] : [])
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
function saveAnnotations(next: ImageAnnotation[]) {
  store.saveImageAnnotations(props.id, next)
  annotationOpen.value = false
}
</script>

<template>
  <div class="workbench-node-component">
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
        <section class="workbench-uploaded-image-node__annotations" aria-label="图片标注操作">
          <span>{{ annotations.length ? `已保存 ${annotations.length} 个标注` : '尚未添加标注' }}</span>
          <button type="button" aria-label="标注图片" :disabled="!url" @click="annotationOpen = true"><Pencil :size="14" aria-hidden="true" />标注图片</button>
        </section>
      </div>
    </WorkbenchNodeFrame>
    <ImageAnnotationDialog :open="annotationOpen" :image-url="url" :model-value="annotations" @close="annotationOpen = false" @save="saveAnnotations" />
  </div>
</template>
