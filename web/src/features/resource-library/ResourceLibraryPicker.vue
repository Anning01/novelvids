<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElDialog } from 'element-plus'
import './dialog.css'
import { useAuthStore } from '@/features/auth/authStore'
import { tr } from '@/i18n'
import type { VideoReferenceMedia } from '@/types'
import { libraryApi } from './api'
import ResourceLibraryBrowser from './ResourceLibraryBrowser.vue'
import type { VideoResource } from './types'

const props = defineProps<{ open: boolean; modelConfigId?: number; maxSelection?: number }>()
const emit = defineEmits<{ close: []; choose: [items: VideoResource[], references: VideoReferenceMedia[]] }>()
const error = ref('')
const busy = ref(false)
let sequence = 0
const auth = useAuthStore()
watch(() => auth.activeTeamId, () => { sequence++; error.value = ''; busy.value = false })
watch(() => props.open, () => { sequence++; error.value = ''; busy.value = false })
async function choose(items: VideoResource[]) {
  if (busy.value) return
  const id = ++sequence
  busy.value = true; error.value = ''
  try {
    const response = props.modelConfigId ? await libraryApi.select(items.map(item => item.id), props.modelConfigId) : null
    if (id === sequence) emit('choose', items, response?.data || [])
  } catch (reason) { if (id === sequence) error.value = (reason as Error).message }
  finally { if (id === sequence) busy.value = false }
}
</script>
<template>
  <ElDialog class="resource-library-dialog" :model-value="open" :title="tr('从资源库选择视频')" width="min(1120px, 96vw)" append-to-body destroy-on-close @close="emit('close')">
    <p v-if="error" role="alert" class="picker-error">{{ error }}</p>
    <p v-if="busy" role="status">{{ tr('正在校验模型限制…') }}</p>
    <ResourceLibraryBrowser v-if="open" pick :max-selection="maxSelection" @choose="choose" />
  </ElDialog>
</template>
<style scoped>.picker-error { color:var(--app-danger,#c54d4d); }</style>
