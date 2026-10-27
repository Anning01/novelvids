<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElDialog } from 'element-plus'
import './dialog.css'
import AppSelect from '@/components/AppSelect.vue'
import { FolderPlus } from 'lucide-vue-next'
import { tr } from '@/i18n'
import { useAuthStore } from '@/features/auth/authStore'
import { notice } from '@/shared/notice'
import { libraryApi } from './api'
import type { ResourceFolder, ResourceImport } from './types'

const props = defineProps<{ source: ResourceImport; disabled?: boolean }>()
const auth = useAuthStore()
const editable = computed(() => auth.enabled === false || ['admin', 'creator', 'super'].includes(auth.role || ''))
const open = ref(false)
const folders = ref<ResourceFolder[]>([])
const folderId = ref(0)
const name = ref('')
const busy = ref(false)
const error = ref('')
let sequence = 0
watch(() => auth.activeTeamId, () => { sequence++; open.value = false; folders.value = [] })
async function show() {
  const id = ++sequence
  open.value = true; busy.value = true; name.value = props.source.name; folderId.value = 0; error.value = ''
  try { const response = await libraryApi.folders(); if (id === sequence) folders.value = response.data.filter(item => !item.deleting) }
  catch (reason) { if (id === sequence) error.value = (reason as Error).message }
  finally { if (id === sequence) busy.value = false }
}
function path(folder: ResourceFolder) {
  const parent = folders.value.find(item => item.id === folder.parent_id)
  return parent ? `${parent.name} / ${folder.name}` : folder.name
}
const folderOptions = computed(() => [
  { value: '0', label: tr('未分类') },
  ...folders.value.map(folder => ({ value: String(folder.id), label: path(folder) })),
])
async function save() {
  if (busy.value) return
  const id = sequence
  busy.value = true; error.value = ''
  try {
    await libraryApi.import({ ...props.source, name: name.value, folder_id: folderId.value })
    if (id === sequence) { open.value = false; notice.success(tr('已存入团队资源库')) }
  } catch (reason) { if (id === sequence) error.value = (reason as Error).message }
  finally { if (id === sequence) busy.value = false }
}
</script>
<template>
  <AppButton v-if="editable" size="sm" :disabled="disabled" @click.stop="show"><FolderPlus :size="14" />{{ tr('存入资源库') }}</AppButton>
  <ElDialog class="resource-library-dialog" v-model="open" :title="tr('存入团队资源库')" width="440px" append-to-body>
    <form class="library-save" @submit.prevent="save"><label>{{ tr('视频名称') }}<input v-model="name" maxlength="255" required></label><label>{{ tr('目标文件夹') }}<AppSelect :menu-z-index="3000" :model-value="String(folderId)" :options="folderOptions" :ariaLabel="tr('目标文件夹')" :disabled="busy" @update:model-value="folderId = Number($event)" /></label><p>{{ tr('保存独立副本，原项目视频保持不变') }}</p><p v-if="error" role="alert">{{ error }}</p><AppButton type="submit" variant="primary" :disabled="busy || !name.trim()" :loading="busy">{{ tr('保存') }}</AppButton></form>
  </ElDialog>
</template>
<style scoped>.library-save { display:grid; gap:16px; }.library-save label { display:grid; gap:8px; }.library-save input { padding:10px; color:var(--app-text); background:var(--app-surface); border:1px solid var(--app-border); border-radius:8px; }.library-save p { font-size:12px; color:var(--app-text-muted); }.library-save [role=alert] { color:var(--app-danger,#c54d4d); }</style>
