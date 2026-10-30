<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { Download, ImageIcon } from 'lucide-vue-next'
import AppButton from './AppButton.vue'
import { api, mediaUrl } from '@/api'
import { useAuthStore } from '@/features/auth/authStore'
import { tr } from '@/i18n'
import { downloadFile } from '@/shared/downloadFile'
import { notice } from '@/shared/notice'
import type { Video } from '@/types'

const props = defineProps<{ video: Video }>()
const emit = defineEmits<{ extracted: [video: Video] }>()
const auth = useAuthStore()
const busy = ref(false)
const canWrite = computed(() => !auth.enabled || auth.isSuperAdmin || ['admin', 'creator'].includes(auth.role || ''))
const frameUrl = computed(() => {
  const metadata = props.video.metadata
  return metadata && ['provider', 'ffmpeg'].includes(String(metadata.last_frame_source)) && typeof metadata.last_frame_url === 'string'
    ? metadata.last_frame_url : ''
})
let alive = true
onBeforeUnmount(() => { alive = false })

async function extractOrDownload() {
  if (busy.value) return
  busy.value = true
  const id = props.video.id
  try {
    if (frameUrl.value) {
      await downloadFile(mediaUrl(frameUrl.value), `last-frame-${id}.png`)
    } else {
      const { data } = await api.extractVideoLastFrame(id)
      if (!alive || props.video.id !== id) return
      emit('extracted', data)
      notice.success(data.metadata?.last_frame_injected_scene_id
        ? tr('尾帧已提取，并加入下一分镜参考图') : tr('尾帧已提取，可下载使用'))
    }
  } catch (error) {
    if (alive && props.video.id === id) notice.error((error as Error).message)
  } finally {
    if (alive) busy.value = false
  }
}
</script>

<template>
  <AppButton v-if="video.status === 3 && video.url && (canWrite || frameUrl)" class="last-frame-button" variant="ghost" size="sm" :loading="busy" :title="frameUrl ? tr('下载尾帧') : tr('从现有视频提取并加入下一分镜参考图，不重新生成')" @click.stop="extractOrDownload">
    <Download v-if="frameUrl && !busy" :size="14" /><ImageIcon v-else-if="!busy" :size="14" />
    {{ frameUrl ? tr('下载尾帧') : tr('提取尾帧') }}
  </AppButton>
</template>

<style scoped>
.last-frame-button { color: var(--app-text-secondary); }
.last-frame-button:hover:not(:disabled) { color: var(--app-accent); background: var(--app-accent-soft); }
.last-frame-button:focus-visible { outline: 2px solid var(--app-accent); outline-offset: 2px; }
</style>
