<script setup lang="ts">
import { computed, onBeforeUnmount, watch, ref } from 'vue'
import { api, sleep } from '@/api'
import { tr } from '@/i18n'
import { GalleryHorizontalEnd } from 'lucide-vue-next'
import AppButton from './AppButton.vue'
import ImageModelSelect from './ImageModelSelect.vue'
import type { Scene } from '@/types'
const props = defineProps<{ scene: Scene; enabled: boolean; canUse?: boolean; beforeGenerate?: () => Promise<void> }>()
const emit = defineEmits<{ updated: [scene: Scene]; use: []; submitted: [taskId: string] }>()
const busy = ref(false)
const submitting = ref(false)
const error = ref('')
const imageModelId = ref('')
const failed = ref(false)
let controller: AbortController | null = null
const sheet = computed(() => props.scene.metadata?.storyboard_sheet as {image_url?: string; previous_image_url?: string; task_id?: string; status?: string} | undefined)
const image = computed(() => sheet.value?.image_url || sheet.value?.previous_image_url)
async function follow(taskId: string) {
  if (busy.value) return
  const current = new AbortController()
  controller?.abort()
  controller = current
  busy.value = true
  error.value = ''
  try {
    for (;;) {
      const task = (await api.task(taskId, current.signal)).data
      if (!imageModelId.value && task.request_params?.model_config_id) imageModelId.value = String(task.request_params.model_config_id)
      if ([3, 4, 5].includes(task.status)) {
        if (task.status !== 3) {
          failed.value = true
          const detail = task.error_message || ''
          throw new Error(detail && !/核对|(?:manual|pending|needs) review/i.test(detail) ? detail : tr('故事版未完成，可重新生成。'))
        }
        const scene = (await api.scene(props.scene.id)).data
        if (!task.response_data?.saved) throw new Error(tr('分镜已更新，请重新生成故事版'))
        failed.value = false
        emit('updated', scene)
        break
      }
      await sleep(1500)
      if (current.signal.aborted) return
    }
  } catch (caught) {
    if (!current.signal.aborted) { failed.value = true; error.value = (caught as Error).message }
  } finally {
    if (controller === current) busy.value = false
  }
}
async function generate() {
  if (busy.value || submitting.value || !imageModelId.value) return
  const restart = failed.value
  submitting.value = true
  error.value = ''
  failed.value = false
  try {
    await props.beforeGenerate?.()
    const task = (await (restart
      ? api.generateStoryboardSheet(props.scene.id, Number(imageModelId.value), true)
      : api.generateStoryboardSheet(props.scene.id, Number(imageModelId.value)))).data
    emit('submitted', task.id)
    await follow(task.id)
  } catch (caught) { failed.value = true; error.value = (caught as Error).message }
  finally { submitting.value = false }
}
watch(() => [props.scene.id, sheet.value?.task_id], () => {
  const data = sheet.value
  if (data?.task_id && data.status !== 'completed') void follow(data.task_id)
}, {immediate: true})
onBeforeUnmount(() => controller?.abort())
</script>

<template>
  <div class="sheet-actions">
    <ImageModelSelect v-if="enabled" v-model="imageModelId" :label="tr('线稿生图模型')"
      :empty-label="tr('请选择生图模型')" :disabled="busy || submitting" />
    <AppButton v-if="enabled" variant="secondary" size="sm" :aria-label="failed ? tr('重置并重试') : image ? tr('重新生成故事版') : tr('生成故事版')" :title="failed ? tr('重置并重试') : image ? tr('重新生成故事版') : tr('生成故事版')" :loading="busy || submitting" :disabled="busy || submitting || !imageModelId" @click="generate">
      <GalleryHorizontalEnd v-if="!busy && !submitting" :size="15" />{{ busy || submitting ? tr('生成中') : failed ? tr('重置并重试') : image ? tr('重新生成故事版') : tr('生成故事版') }}
    </AppButton>
    <AppButton v-if="image && canUse" variant="ghost" size="sm" @click="emit('use')">{{ tr('使用故事版参考') }}</AppButton>
    <small v-if="error && enabled" role="alert">{{ error }}</small>
  </div>
</template>

<style scoped>
.sheet-actions { display:flex; flex-wrap:wrap; align-items:center; gap:6px; }
small { color:var(--creation-danger); }
</style>
