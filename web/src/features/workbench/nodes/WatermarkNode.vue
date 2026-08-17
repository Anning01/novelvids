<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { Droplet, LoaderCircle, Settings2 } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { api, mediaUrl } from '@/api'
import { notice } from '@/shared/notice'
import WatermarkSettingsDialog from '../components/WatermarkSettingsDialog.vue'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
import { normalizeWatermarkConfig, type WatermarkConfig } from '../config/watermarkConfig'
import { useWorkbenchStore } from '../store/workbenchStore'

const props = defineProps<NodeProps>()
const store = useWorkbenchStore()
const settingsOpen = ref(false)
const uploading = ref(false)
const node = computed(() => store.nodeByKey(props.id))
const config = computed(() => normalizeWatermarkConfig(
  (node.value?.data.config || props.data.config) as Partial<WatermarkConfig>,
))
const inputNode = computed(() => {
  const input = store.edges.find(item => item.target === props.id && item.targetHandle === 'video-input')
  return input ? store.nodeByKey(input.source) : null
})
const videoUrl = computed(() => {
  if (inputNode.value?.kind === 'video_media') return String(inputNode.value.data.url || '')
  if (inputNode.value?.kind === 'video_result') {
    const video = inputNode.value.data.video as { url?: string } | undefined
    return video?.url || ''
  }
  return ''
})
const disabledReason = computed(() => {
  if (!props.data.apply_capability) return '当前服务未启用水印执行'
  if (!videoUrl.value) return '请先连接视频'
  if (!config.value.resourceUrl) return '请先上传水印图片'
  return '水印执行接口尚未接入'
})

function saveConfig(value: WatermarkConfig) {
  store.saveWatermarkConfig(props.id, value)
}
async function uploadWatermark(file: File) {
  uploading.value = true
  try {
    const uploaded = await api.upload(file)
    saveConfig({
      ...config.value,
      resourceUrl: mediaUrl(`/media/${encodeURIComponent(uploaded.filename)}`),
    })
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '水印图片上传失败')
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <WorkbenchNodeFrame v-bind="props" :data="{ ...data, kind: 'watermark', title: data.title || '新水印', status: 'watermark' }">
    <div class="workbench-watermark-node">
      <div class="workbench-watermark-node__preview" aria-label="水印视频预览">
        <video v-if="videoUrl" :src="videoUrl" controls playsinline preload="metadata" aria-label="水印输入视频" />
        <div v-else class="workbench-media-placeholder">连接视频后预览</div>
        <img
          v-if="config.resourceUrl"
          :src="config.resourceUrl"
          alt="水印预览图"
          :style="{ left: `${config.x * 100}%`, top: `${config.y * 100}%`, width: `${config.scale * 100}%` }"
        >
      </div>
      <div class="workbench-watermark-node__summary">
        <strong>水印配置</strong>
        <span>{{ config.resourceUrl ? '已选择水印图片' : '新水印' }}</span>
        <button type="button" aria-label="设置水印" @click="settingsOpen = true"><Settings2 :size="14" aria-hidden="true" />设置</button>
      </div>
      <div class="workbench-watermark-node__mode">
        <Droplet :size="15" aria-hidden="true" />
        <span><strong>水印配置模式</strong><small>连接视频；配置完成后可由已启用的服务执行。</small></span>
      </div>
      <button type="button" class="workbench-watermark-node__run" :aria-label="disabledReason" :title="disabledReason" disabled>
        <LoaderCircle v-if="uploading" :size="15" aria-hidden="true" />
        {{ disabledReason }}
      </button>
    </div>
    <WatermarkSettingsDialog
      :open="settingsOpen"
      :model-value="config"
      :uploading="uploading"
      @close="settingsOpen = false"
      @change="saveConfig"
      @upload="uploadWatermark"
    />
  </WorkbenchNodeFrame>
</template>
