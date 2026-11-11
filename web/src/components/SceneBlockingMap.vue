<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { API_BASE, authHeaders, mediaUrl } from '@/api'
import { tr } from '@/i18n'
import type { Scene } from '@/types'
import { fetchFileBlob } from '@/shared/downloadFile'

const props = defineProps<{scene: Scene}>()
const archived = computed(() => {
  const media = props.scene.metadata?.imported_media
  const file = Array.isArray(media) && media.find(item => item?.role === 'blocking' && typeof item.url === 'string')
  return file ? mediaUrl(file.url) : ''
})
const plan = computed(() => {
  const data = props.scene.prompt_params
  return Array.isArray(data?.segments) && data.segments.length > 1 ? data.blocking_map : null
})
const rendered = ref('')
const error = ref('')
watch([() => props.scene.id, archived, plan], async ([id, archive, layout], _, cleanup) => {
  let active = true
  let url = ''
  cleanup(() => { active = false; if (url) URL.revokeObjectURL(url) })
  rendered.value = ''
  error.value = ''
  if (archive || !layout) return
  try {
    const blob = await fetchFileBlob(`${API_BASE}/scene/${id}/blocking-map.svg`, authHeaders())
    if (active) rendered.value = url = URL.createObjectURL(blob)
  } catch (e) {
    if (active) error.value = (e as Error).message
  }
}, {immediate: true})
</script>

<template>
  <figure v-if="archived || plan" class="blocking-plan">
    <figcaption>{{ tr('空间定位图') }}</figcaption>
    <img v-if="archived || rendered" :src="archived || rendered" :alt="tr('空间定位图')" loading="lazy" />
    <p v-if="error" role="alert">{{ error }}</p>
  </figure>
</template>

<style scoped>
.blocking-plan { min-width: 0; margin: 0; padding: 12px; border: 1px solid var(--app-border); border-radius: 10px; background: var(--app-surface-muted); color: var(--app-text); }
figcaption { font-size: 14px; font-weight: 650; }
img { display: block; width: 100%; max-height: 360px; object-fit: contain; margin-top: 12px; }
p { color: var(--app-danger); }
</style>
