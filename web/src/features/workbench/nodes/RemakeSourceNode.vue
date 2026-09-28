<script setup lang="ts">
import { tr } from '@/i18n'

import type { NodeProps } from '@vue-flow/core'
import { FileVideo2, HardDrive, History } from 'lucide-vue-next'
import { computed } from 'vue'
import { mediaUrl } from '@/api'
import DeferredVideoPlayer from '@/components/DeferredVideoPlayer.vue'
import type { WorkbenchRemakeSource } from '@/types'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'

const props = defineProps<NodeProps>()
const source = computed(() => props.data.source as WorkbenchRemakeSource)
const sourceUrl = computed(() => mediaUrl(source.value.media_url))
const sourceLabel = computed(() => source.value.source_kind === 'history' ? tr('历史项目') : tr('上传视频'))
const durationLabel = computed(() => {
  const seconds = Math.max(0, Math.round(source.value.duration_seconds || 0))
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
})
const sizeLabel = computed(() => {
  const bytes = Math.max(0, source.value.size_bytes || 0)
  return bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(bytes >= 100 * 1024 * 1024 ? 0 : 1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`
})
</script>

<template>
  <WorkbenchNodeFrame v-bind="props" :data="{ ...data, kind: 'source_video', title: tr('来源视频 · 第 {p0} 集', { p0: source.episode_number }), status: 'ready', borderless_media: true }">
    <div class="workbench-remake-source">
      <DeferredVideoPlayer :src="sourceUrl" :title="source.original_filename" />
      <div class="workbench-remake-source__body">
        <strong><FileVideo2 :size="15" aria-hidden="true" />{{ source.original_filename }}</strong>
        <dl>
          <div><dt>{{ tr('时长') }}</dt><dd>{{ durationLabel }}</dd></div>
          <div><dt>{{ tr('画面') }}</dt><dd>{{ source.width }} × {{ source.height }}</dd></div>
          <div><dt>{{ tr('大小') }}</dt><dd>{{ sizeLabel }}</dd></div>
        </dl>
        <span><History v-if="source.source_kind === 'history'" :size="13" aria-hidden="true" /><HardDrive v-else :size="13" aria-hidden="true" />{{ sourceLabel }} {{ tr('· 不可变来源') }}</span>
      </div>
    </div>
  </WorkbenchNodeFrame>
</template>
