<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { Film, LoaderCircle } from 'lucide-vue-next'
import { authHeaders } from '@/api'
import { tr } from '@/i18n'
import { fetchFileBlob } from '@/shared/downloadFile'
import { finishedApi } from './api'

const props = defineProps<{ versionId: number }>()
const source = ref(''), loading = ref(false), failed = ref(false)
let epoch = 0
function clear() { if (source.value) URL.revokeObjectURL(source.value); source.value = '' }
watch(() => props.versionId, async id => {
  const version = ++epoch
  clear(); loading.value = true; failed.value = false
  try {
    const file = await fetchFileBlob(finishedApi.coverUrl(id), authHeaders())
    if (version === epoch) source.value = URL.createObjectURL(file)
  } catch { if (version === epoch) failed.value = true }
  finally { if (version === epoch) loading.value = false }
}, { immediate: true })
onBeforeUnmount(() => { ++epoch; clear() })
</script>
<template>
  <div class="finished-cover" :aria-busy="loading">
    <img v-if="source" :src="source" :alt="tr('视频第一帧封面')" decoding="async" />
    <LoaderCircle v-else-if="loading" :size="20" class="finished-spinner" aria-hidden="true" />
    <span v-else><Film :size="24" aria-hidden="true" /><small>{{ failed ? tr('封面暂不可用') : tr('成片封面') }}</small></span>
  </div>
</template>
<style scoped>
.finished-cover{aspect-ratio:16/9;display:grid;place-items:center;overflow:hidden;background:var(--app-surface-muted);color:var(--app-text-muted);width:100%}.finished-cover img{width:100%;height:100%;object-fit:cover}.finished-cover>span{display:grid;justify-items:center;gap:5px}.finished-cover small{font-size:11px}
</style>
