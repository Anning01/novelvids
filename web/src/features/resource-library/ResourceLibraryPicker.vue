<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElDialog } from 'element-plus'
import './dialog.css'
import { useAuthStore } from '@/features/auth/authStore'
import { tr } from '@/i18n'
import type { VideoReferenceMedia } from '@/types'
import { libraryApi } from './api'
import ResourceCatalogBrowser from './ResourceCatalogBrowser.vue'
import type { CatalogResource } from './catalog'
import type { VideoResource } from './types'

const props = defineProps<{ open: boolean; modelConfigId?: number; maxSelection?: number; kind?: 'video' | 'image'; allowImages?: boolean; maxImageSelection?: number; maxVideoSelection?: number }>()
const emit = defineEmits<{ close: []; choose: [items: VideoResource[], references: VideoReferenceMedia[]] }>()
const selectedKind=ref<'video'|'image'>(props.kind||'video')
const selectionLimit=computed(()=>selectedKind.value==='image'?(props.maxImageSelection??props.maxSelection):(props.maxVideoSelection??props.maxSelection))
const error = ref('')
const busy = ref(false)
let sequence = 0
const auth = useAuthStore()
watch(() => auth.activeTeamId, () => { sequence++; error.value = ''; busy.value = false })
watch(() => props.open, () => { sequence++; error.value = ''; busy.value = false })
async function choose(rows: CatalogResource[]) {
  const items: VideoResource[] = rows.filter(row => row.catalog === 'media').map(row => ({ id: row.id, name: row.name, folder_id: row.folder_id, filename: row.filename || row.name, url: row.url, storage_ref: row.storage_ref || row.url, poster_url: row.poster_url || '', state: 'ready', created_at: row.created_at, duration: row.duration || 0, width: row.width || 0, height: row.height || 0, fps: 0, codec: '', content_type: '', size_bytes: row.size_bytes || 0 }))
  if (busy.value) return
  const id = ++sequence
  busy.value = true; error.value = ''
  try {
    const response = props.modelConfigId && items.length ? await libraryApi.select(items.map(item => item.id), props.modelConfigId) : null
    if (id === sequence) emit('choose', items, [...(response?.data || []), ...rows.filter(row => row.catalog === 'asset' && row.kind === 'image').map(row => ({ type: 'image' as const, url: row.url, name: row.name }))])
  } catch (reason) { if (id === sequence) error.value = (reason as Error).message }
  finally { if (id === sequence) busy.value = false }
}
</script>
<template>
  <ElDialog class="resource-library-dialog resource-library-dialog--picker" :model-value="open" :title="tr(kind === 'image' ? '从资源库选择图片' : '从资源库选择视频')" width="min(1120px, 96vw)" align-center append-to-body destroy-on-close @close="emit('close')">
    <p class="resource-picker-hint">{{ tr('选择素材作为参考，已选资源会添加到当前分镜。') }}</p>
    <p v-if="error" role="alert" class="picker-error">{{ error }}</p>
    <p v-if="busy" role="status">{{ tr('正在校验模型限制…') }}</p>
    <ResourceCatalogBrowser v-if="open" pick :kind="allowImages ? undefined : kind || 'video'" :allowed-kinds="allowImages ? ['video','image'] : undefined" :max-selection="selectionLimit" @change-kind="value => { if (value === 'image' || value === 'video') selectedKind = value }" @choose="choose" />
  </ElDialog>
</template>
<style scoped>.picker-error { color:var(--app-danger,#c54d4d); }</style>
