<script setup lang="ts">
import { computed, onBeforeUnmount, watch, ref } from 'vue'
import { api, mediaUrl, sleep } from '@/api'
import { tr } from '@/i18n'
import AppButton from './AppButton.vue'
import type { Scene } from '@/types'
const props = defineProps<{ scene: Scene; enabled: boolean; canUse?: boolean }>()
const emit = defineEmits<{ updated: [scene: Scene]; use: [] }>()
const busy = ref(false)
const submitting = ref(false)
const error = ref('')
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
      if ([3, 4, 5].includes(task.status)) {
        if (task.status !== 3) throw new Error(task.error_message || tr('故事版未完成'))
        const scene = (await api.scene(props.scene.id)).data
        if (!task.response_data?.saved) throw new Error(tr('分镜已更新，请重新生成故事版'))
        emit('updated', scene)
        break
      }
      await sleep(1500)
      if (current.signal.aborted) return
    }
  } catch (caught) {
    if (!current.signal.aborted) error.value = (caught as Error).message
  } finally {
    if (controller === current) busy.value = false
  }
}
async function generate() {
  if (busy.value || submitting.value) return
  submitting.value = true
  error.value = ''
  try {
    const task = (await api.generateStoryboardSheet(props.scene.id)).data
    await follow(task.id)
  } catch (caught) { error.value = (caught as Error).message }
  finally { submitting.value = false }
}
watch(() => [props.scene.id, sheet.value?.task_id], () => {
  const data = sheet.value
  if (data?.task_id && data.status === 'pending') void follow(data.task_id)
}, {immediate: true})
onBeforeUnmount(() => controller?.abort())
</script>

<template>
  <section class="sheet-card" :aria-label="tr('逐镜线稿故事版')">
    <header><strong>{{ tr('逐镜线稿故事版') }}</strong><AppButton v-if="enabled" variant="secondary" size="sm" :loading="busy || submitting" :disabled="busy || submitting" @click="generate">{{ busy || submitting ? tr('生成中') : image ? tr('重新生成故事版') : tr('生成故事版') }}</AppButton></header>
    <a v-if="image" :href="mediaUrl(image)" target="_blank" rel="noopener"><img :src="mediaUrl(image)" :alt="tr('分镜 {p0} 的线稿故事版', {p0: scene.sequence})" loading="lazy" /></a>
    <AppButton v-if="image && canUse" variant="secondary" size="sm" @click="emit('use')">{{ tr('使用故事版参考') }}</AppButton>
    <p v-else-if="!image" role="status">{{ busy ? tr('正在绘制本镜故事版') : tr('尚未生成故事版') }}</p>
    <p v-if="error" class="sheet-error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.sheet-card { padding: 12px; border: 1px solid var(--app-border); border-radius: 10px; color: var(--app-text); background: var(--app-surface-muted); }
header { display:flex; justify-content:space-between; align-items:center; gap:12px; }
img { display:block; width:100%; max-height:360px; object-fit:contain; margin-top:12px; border-radius:6px; }
p { color:var(--app-text-secondary); font-size:13px; margin:10px 0 0; }
.sheet-error { color: var(--app-danger, var(--app-text)); }
</style>
