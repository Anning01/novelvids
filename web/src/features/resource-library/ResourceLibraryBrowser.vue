<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElDialog } from 'element-plus'
import './dialog.css'
import { Folder, FolderPlus, Upload, Search, MoveRight, Trash2, Pencil, Play, Film, MoreHorizontal, LoaderCircle, CheckCircle2, CircleAlert } from 'lucide-vue-next'
import AppSelect from '@/components/AppSelect.vue'
import { mediaUrl } from '@/api'
import { tr } from '@/i18n'
import { useAuthStore } from '@/features/auth/authStore'
import { appConfirm } from '@/shared/confirmDialog'
import { notice } from '@/shared/notice'
import { libraryApi } from './api'
import type { LibraryCapabilities, ResourceFolder, VideoResource } from './types'

const props = withDefaults(defineProps<{ pick?: boolean; maxSelection?: number }>(), { maxSelection: 100 })
const emit = defineEmits<{ choose: [items: VideoResource[]] }>()
const auth = useAuthStore()
const editable = computed(() => auth.enabled === false || ['admin', 'creator', 'super'].includes(auth.role || ''))
const libraryRoot = ref<HTMLElement | null>(null)
function closeFolderMenus(event?: Event) {
  for (const menu of libraryRoot.value?.querySelectorAll<HTMLDetailsElement>('.folder-menu[open]') || []) {
    if (event?.type === 'pointerdown' && event.target instanceof Node && menu.contains(event.target)) continue
    menu.open = false
    if (event instanceof KeyboardEvent) menu.querySelector<HTMLElement>('summary')?.focus()
  }
}
function handleMenuKey(event: KeyboardEvent) {
  if (event.key === 'Escape') closeFolderMenus(event)
}
onMounted(() => {
  document.addEventListener('pointerdown', closeFolderMenus)
  document.addEventListener('keydown', handleMenuKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', closeFolderMenus)
  document.removeEventListener('keydown', handleMenuKey)
})
const folders = ref<ResourceFolder[]>([])
const items = ref<VideoResource[]>([])
const folderId = ref<number | null>(null)
const search = ref('')
const page = ref(1)
const pages = ref(0)
const total = ref(0)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const selected = ref<VideoResource[]>([])
const capabilities = ref<LibraryCapabilities | null>(null)
const input = ref<HTMLInputElement>()
const preview = ref<VideoResource | null>(null)
const editFolder = ref<{ id?: number; name: string; parent_id: number } | null>(null)
const renameItem = ref<VideoResource | null>(null)
const renameValue = ref('')
const moving = ref(false)
const targetFolder = ref(0)
const dragging = ref<number[]>([])
interface UploadJob { file: File; folder: number; folderLabel: string; progress: number; status: 'waiting' | 'preparing' | 'uploading' | 'processing' | 'done' | 'failed'; error: string; epoch: number }
const jobs = ref<UploadJob[]>([])
const uploadDialogOpen = ref(false)
const activeUploads = computed(() => jobs.value.filter(job => !['done', 'failed'].includes(job.status)).length)
const completedUploads = computed(() => jobs.value.filter(job => job.status === 'done').length)
const failedUploads = computed(() => jobs.value.filter(job => job.status === 'failed').length)
const uploadSummary = computed(() => activeUploads.value
  ? tr('正在处理 {p0} 个视频', { p0: activeUploads.value })
  : tr('上传结束：成功 {p0} 个，失败 {p1} 个', { p0: completedUploads.value, p1: failedUploads.value }))
function uploadStatus(job: UploadJob) {
  if (job.status === 'waiting') return tr('等待上传')
  if (job.status === 'preparing') return tr('正在准备上传…')
  if (job.status === 'uploading') return tr('上传中 {p0}%', { p0: job.progress })
  if (job.status === 'processing') return tr('上传已完成，正在校验视频并生成封面…')
  if (job.status === 'done') return tr('上传成功，已存入资源库')
  return tr('上传失败')
}
function viewUploadFolder(job: UploadJob) {
  uploadDialogOpen.value = false
  browse(job.folder)
}
let epoch = 0
let loadId = 0
const roots = computed(() => folders.value.filter(item => !item.parent_id))
const orderedFolders = computed(() => roots.value.flatMap(root => [root, ...folders.value.filter(child => child.parent_id === root.id)]))
const parentFolderOptions = computed(() => [
  { value: '0', label: tr('根目录') },
  ...roots.value.filter(item => item.id !== editFolder.value?.id && !item.deleting)
    .map(item => ({ value: String(item.id), label: item.name })),
])
const destinationFolderOptions = computed(() => [
  { value: '0', label: tr('未分类') },
  ...orderedFolders.value.filter(item => !item.deleting)
    .map(item => ({ value: String(item.id), label: path(item.id) })),
])
const currentFolder = computed(() => folders.value.find(item => item.id === folderId.value))
function path(id: number): string {
  const folder = folders.value.find(item => item.id === id)
  if (!folder) return tr('未分类')
  const parent = folders.value.find(item => item.id === folder.parent_id)
  return parent ? `${parent.name} / ${folder.name}` : folder.name
}
const selectedIds = computed(() => selected.value.map(item => item.id))
const allPageSelected = computed(() => items.value.length > 0 && items.value.filter(item => item.state === 'ready').every(item => selectedIds.value.includes(item.id)))

async function load() {
  const requestId = ++loadId
  loading.value = true; error.value = ''
  try {
    const response = await libraryApi.list(folderId.value, search.value, page.value)
    if (requestId !== loadId) return
    items.value = response.data.items
    pages.value = response.data.pagination.pages
    total.value = response.data.pagination.total
  } catch (reason) { if (requestId === loadId) error.value = reason instanceof Error ? reason.message : tr('资源库加载失败') }
  finally { if (requestId === loadId) loading.value = false }
}
async function refresh() {
  const expectedEpoch = epoch
  const response = await libraryApi.folders()
  if (expectedEpoch !== epoch) return
  folders.value = response.data
  if (folderId.value && !folders.value.some(item => item.id === folderId.value && !item.deleting)) folderId.value = null
  await load()
}
async function initialize() {
  const expectedEpoch = ++epoch
  loadId++; selected.value = []; jobs.value = []; uploadDialogOpen.value = false; items.value = []; folders.value = []; preview.value = null
  editFolder.value = null; renameItem.value = null; moving.value = false; folderId.value = null; search.value = ''; page.value = 1
  capabilities.value = null
  try {
    const response = await libraryApi.capabilities()
    if (expectedEpoch !== epoch) return
    capabilities.value = response.data
    await refresh()
  } catch (reason) { if (expectedEpoch === epoch) error.value = (reason as Error).message }
}
watch(() => auth.activeTeamId, initialize, { immediate: true })
function browse(id: number | null) { closeFolderMenus(); folderId.value = id; page.value = 1; search.value = ''; void load() }
function submitSearch() { page.value = 1; void load() }
function toggle(item: VideoResource) {
  if (item.state !== 'ready') return
  if (selectedIds.value.includes(item.id)) selected.value = selected.value.filter(value => value.id !== item.id)
  else if (selected.value.length < props.maxSelection) selected.value.push(item)
  else notice.info(tr('最多选择 {p0} 个视频', { p0: props.maxSelection }))
}
function togglePage() {
  if (allPageSelected.value) selected.value = selected.value.filter(item => !items.value.some(value => value.id === item.id))
  else for (const item of items.value) if (!selectedIds.value.includes(item.id)) toggle(item)
}
async function action(callback: () => Promise<unknown>) {
  if (busy.value) return
  busy.value = true; error.value = ''
  let actionError = ''
  try { await callback() }
  catch (reason) { actionError = (reason as Error).message }
  finally {
    try { await refresh() } catch (reason) { error.value = (reason as Error).message }
    if (actionError) error.value = actionError
    busy.value = false
  }
}
function newFolder() { closeFolderMenus(); editFolder.value = { name: '', parent_id: currentFolder.value?.parent_id === 0 ? currentFolder.value.id : 0 } }
function saveFolder() {
  const value = editFolder.value
  if (!value) return
  void action(async () => { await libraryApi.writeFolder(value.name, value.parent_id, value.id); editFolder.value = null })
}
function saveRename() {
  const item = renameItem.value
  if (item) void action(async () => { await libraryApi.rename(item.id, renameValue.value); renameItem.value = null })
}
async function moveTo(id: number, ids = [...selectedIds.value]) {
  if (!ids.length) return
  await action(async () => { await libraryApi.move(ids, id); selected.value = []; moving.value = false; notice.success(tr('已移动')) })
}
function drop(event: DragEvent, id: number) {
  event.preventDefault()
  if (!editable.value || busy.value) return
  const ids = [...dragging.value]; dragging.value = []
  if (ids.length) void moveTo(id, ids)
}
function startDrag(event: DragEvent, item: VideoResource) {
  if (!editable.value || item.state !== 'ready') { event.preventDefault(); return }
  dragging.value = selectedIds.value.includes(item.id) ? [...selectedIds.value] : [item.id]
  event.dataTransfer?.setData('text/plain', JSON.stringify(dragging.value))
}
async function remove(ids: number[]) {
  const confirmed = await appConfirm({ title: tr('永久删除 {p0} 个视频？', { p0: ids.length }), message: tr('将删除视频及封面，包括 OSS 文件。不可恢复，已引用的分镜和画布可能失效。'), confirmLabel: tr('永久删除'), tone: 'danger' })
  if (!confirmed) return
  await action(async () => {
    const response = await libraryApi.delete(ids)
    selected.value = []
    const failed = response.data.filter(item => !item.deleted)
    if (failed.length) throw new Error(tr('{p0} 个文件删除失败，请点击重试删除', { p0: failed.length }))
  })
}
async function removeFolder(folder: ResourceFolder) {
  closeFolderMenus()
  try {
    const response = await libraryApi.deletePreview(folder.id)
    const confirmed = await appConfirm({ title: tr('永久删除文件夹“{p0}”？', { p0: folder.name }), message: tr('包含 {p0} 个视频。将删除全部子文件夹、视频及 OSS 文件。不可恢复，已引用的分镜和画布可能失效。', { p0: response.data.resource_count }), confirmLabel: tr('永久删除'), tone: 'danger' })
    if (confirmed) await action(async () => {
      const result = await libraryApi.deleteFolder(folder.id)
      if (result.data.some(item => !item.deleted)) notice.error(tr('部分文件删除失败，请重试删除文件夹'))
    })
  } catch (reason) { error.value = (reason as Error).message }
}
async function runJob(job: UploadJob) {
  if (job.epoch !== epoch || ['preparing', 'uploading', 'processing'].includes(job.status)) return
  job.status = 'preparing'; job.error = ''; job.progress = 0
  try {
    const limits = capabilities.value
    if (!limits) throw new Error(tr('上传配置尚未就绪，请稍后重试'))
    if (!job.file.size || job.file.size > limits.max_size_mb * 1024 * 1024 || !limits.formats.includes(job.file.name.split('.').pop()?.toLowerCase() || '')) {
      throw new Error(tr('仅支持非空 MP4/MOV，单文件不超过 {p0}MB', { p0: limits.max_size_mb }))
    }
    await libraryApi.upload(job.file, job.folder, value => {
      job.progress = Math.max(0, Math.min(100, value))
      job.status = job.progress >= 100 ? 'processing' : 'uploading'
    })
    job.progress = 100
    job.status = 'done'
    if (job.epoch === epoch) notice.success(tr('视频“{p0}”上传成功', { p0: job.file.name }))
  } catch (reason) {
    job.status = 'failed'; job.error = (reason as Error).message
    if (job.epoch === epoch) notice.error(tr('视频“{p0}”上传失败', { p0: job.file.name }))
  }
  if (job.epoch === epoch) await load()
}
async function uploadFiles(event: Event) {
  const target = event.target as HTMLInputElement
  const files = Array.from(target.files || []); target.value = ''
  if (!files.length) return
  const folder = folderId.value || 0
  const batch = files.map(file => ({ file, folder, folderLabel: path(folder), progress: 0, status: 'waiting' as const, error: '', epoch }))
  jobs.value.push(...batch)
  const queued = jobs.value.slice(-batch.length)
  uploadDialogOpen.value = true
  // Render the queue before starting network work; do not add artificial progress delays.
  await nextTick()
  for (const job of queued) await runJob(job)
}

</script>

<template>
  <section ref="libraryRoot" class="resource-library" :class="{ 'is-picker': pick }">
    <header v-if="!pick" class="library-heading"><div><h1>{{ tr('团队视频资源库') }}</h1><p>{{ tr('跨项目共享视频，移动文件不会改变引用地址') }}</p></div><div class="library-actions" v-if="editable"><AppButton :disabled="busy" @click="newFolder"><FolderPlus :size="16" />{{ tr('新建文件夹') }}</AppButton><AppButton variant="primary" :disabled="!capabilities" @click="input?.click()"><Upload :size="16" />{{ tr('上传视频') }}</AppButton></div></header>
    <input v-if="editable" ref="input" class="library-file-input" type="file" multiple accept=".mp4,.mov" @change="uploadFiles">
    <div class="library-body">
      <aside class="library-folders" :aria-label="tr('资源文件夹')">
        <button :class="{ active: folderId === null }" :aria-current="folderId === null ? 'page' : undefined" @click="browse(null)"><Film :size="16" />{{ tr('全部视频') }}</button>
        <button :class="{ active: folderId === 0 }" :aria-current="folderId === 0 ? 'page' : undefined" @click="browse(0)" @dragover.prevent @drop="drop($event, 0)"><Folder :size="16" />{{ tr('未分类') }}</button>
        <div v-for="folder in orderedFolders" :key="folder.id" class="library-folder-row" :class="{ nested: folder.parent_id, active: folderId === folder.id }" @dragover.prevent @drop="drop($event, folder.id)">
          <button :disabled="folder.deleting" :aria-current="folderId === folder.id ? 'page' : undefined" @click="browse(folder.id)"><Folder :size="16" /><span>{{ folder.name }}</span></button>
          <details v-if="editable" class="folder-menu"><summary :aria-label="tr('管理文件夹 {p0}', { p0: folder.name })"><MoreHorizontal :size="18" aria-hidden="true" /></summary><div><button :disabled="folder.deleting" @click="closeFolderMenus(); editFolder = { ...folder }">{{ tr('改名 / 移动') }}</button><button class="danger" @click="removeFolder(folder)">{{ tr(folder.deleting ? '重试删除' : '删除文件夹') }}</button></div></details>
        </div>
      </aside>
      <main class="library-main">
        <div class="library-toolbar">
          <form class="library-search" @submit.prevent="submitSearch"><Search :size="17" /><input v-model="search" :placeholder="tr('搜索整个团队的视频')" :aria-label="tr('搜索视频')"><AppButton type="submit">{{ tr('搜索') }}</AppButton></form>
          <div v-if="pick && editable" class="library-actions">
            <AppButton size="sm" :disabled="busy" @click="newFolder"><FolderPlus :size="15" />{{ tr('新建文件夹') }}</AppButton>
            <AppButton size="sm" variant="primary" :disabled="!capabilities" @click="input?.click()"><Upload :size="15" />{{ tr('上传视频') }}</AppButton>
          </div>
        </div>
        <div class="library-selection"><span>{{ search ? tr('搜索结果') : folderId === null ? tr('全部视频') : path(folderId) }} · {{ total }}</span><div><AppButton size="sm" :disabled="!items.length" @click="togglePage">{{ tr(allPageSelected ? '取消本页选择' : '选择本页') }}</AppButton><span>{{ tr('已选 {p0} 个', { p0: selected.length }) }}</span><template v-if="editable && !pick"><AppButton size="sm" :disabled="!selected.length || busy" @click="targetFolder = folderId || 0; moving = true"><MoveRight :size="14" />{{ tr('移动到') }}</AppButton><AppButton size="sm" variant="danger" :disabled="!selected.length || busy" @click="remove([...selectedIds])"><Trash2 :size="14" />{{ tr('删除') }}</AppButton></template></div></div>
        <p v-if="error" class="library-error" role="alert">{{ error }} <AppButton size="sm" @click="load">{{ tr('刷新列表') }}</AppButton></p>
        <div v-if="jobs.length" class="library-upload-summary" role="status" aria-live="polite">
          <LoaderCircle v-if="activeUploads" class="upload-spinner" :size="20" aria-hidden="true" />
          <CircleAlert v-else-if="failedUploads" :size="20" aria-hidden="true" />
          <CheckCircle2 v-else :size="20" aria-hidden="true" />
          <div><strong>{{ uploadSummary }}</strong><small>{{ tr('选择视频后可在这里查看上传进度和结果') }}</small></div>
          <AppButton size="sm" @click="uploadDialogOpen = true">{{ tr('查看上传详情') }}</AppButton>
        </div>
        <p v-if="loading" role="status">{{ tr('正在加载资源…') }}</p>
        <div class="library-grid" :aria-busy="loading">
          <article v-for="item in items" :key="item.id" class="library-card" :class="{ selected: selectedIds.includes(item.id) }" :draggable="editable && item.state === 'ready'" @dragstart="startDrag($event, item)" @dragend="dragging = []">
            <div class="library-cover"><button :disabled="item.state !== 'ready'" :aria-label="tr('预览 {p0}', { p0: item.name })" @click="preview = item"><img v-if="item.poster_url" :src="mediaUrl(item.poster_url)" alt="" loading="lazy"><Film v-else :size="30" /><Play class="library-play" :size="28" /></button><input type="checkbox" :checked="selectedIds.includes(item.id)" :disabled="item.state !== 'ready'" :aria-label="tr('选择 {p0}', { p0: item.name })" @change="toggle(item)"><small>{{ item.duration?.toFixed(1) }}s</small></div>
            <div class="library-card-info"><strong :title="item.name">{{ item.name }}</strong><small>{{ path(item.folder_id) }} · {{ item.width }}×{{ item.height }}</small><div v-if="editable && !pick" class="library-card-actions"><AppButton size="sm" :disabled="item.state !== 'ready'" :aria-label="tr('重命名 {p0}', { p0: item.name })" @click="renameItem = item; renameValue = item.name"><Pencil :size="14" /></AppButton><AppButton size="sm" :disabled="busy" :aria-label="tr('删除 {p0}', { p0: item.name })" @click="remove([item.id])"><Trash2 :size="14" />{{ item.state !== 'ready' ? tr('重试删除') : '' }}</AppButton></div><p v-if="item.state !== 'ready'" class="library-error">{{ tr('删除处理中或失败，无法引用') }}</p></div>
          </article>
        </div>
        <div v-if="!loading && !items.length && !activeUploads" class="library-empty"><Film :size="40" /><strong>{{ tr('这里还没有视频') }}</strong><p>{{ tr('上传视频，或从项目中手动存入资源库') }}</p></div>
        <footer class="library-footer"><div><AppButton :disabled="page <= 1 || loading" @click="page--; load()">{{ tr('上一页') }}</AppButton><span>{{ page }} / {{ pages || 1 }}</span><AppButton :disabled="page >= pages || loading" @click="page++; load()">{{ tr('下一页') }}</AppButton></div><AppButton v-if="pick" variant="primary" :disabled="!selected.length || busy" @click="emit('choose', selected)">{{ tr('使用所选视频（{p0}）', { p0: selected.length }) }}</AppButton></footer>
      </main>
    </div>
    <ElDialog class="resource-library-dialog" v-model="uploadDialogOpen" :title="tr('视频上传')" width="640px" append-to-body>
      <section class="library-upload-panel" aria-live="polite" :aria-busy="activeUploads > 0">
        <header><strong>{{ uploadSummary }}</strong><p>{{ activeUploads ? tr('可以关闭此窗口继续浏览，上传会在当前页面继续进行。请勿刷新或离开页面。') : tr('上传结果会保留在页面中，可随时查看。') }}</p></header>
        <article v-for="(job, index) in jobs" :key="index" class="library-upload-job" :class="`is-${job.status}`">
          <div class="upload-job-heading"><Film :size="20" aria-hidden="true" /><div><strong :title="job.file.name">{{ job.file.name }}</strong><small>{{ tr('保存到：{p0}', { p0: job.folderLabel }) }} · {{ (job.file.size / 1024 / 1024).toFixed(1) }} MB</small></div><CheckCircle2 v-if="job.status === 'done'" :size="20" aria-hidden="true" /><CircleAlert v-else-if="job.status === 'failed'" :size="20" aria-hidden="true" /><LoaderCircle v-else class="upload-spinner" :size="20" aria-hidden="true" /></div>
          <progress v-if="job.status !== 'failed'" :value="['waiting', 'preparing', 'processing'].includes(job.status) ? undefined : job.progress" max="100" :aria-label="tr('上传进度：{p0}', { p0: job.file.name })" />
          <p class="upload-job-status">{{ uploadStatus(job) }}</p>
          <p v-if="job.error" role="alert" class="library-error">{{ job.error }}</p>
          <div class="upload-job-actions"><AppButton v-if="job.status === 'failed'" size="sm" @click="runJob(job)">{{ tr('重试上传') }}</AppButton><AppButton v-if="job.status === 'done'" size="sm" @click="viewUploadFolder(job)">{{ tr('查看所在文件夹') }}</AppButton></div>
        </article>
        <footer><AppButton variant="primary" @click="uploadDialogOpen = false">{{ activeUploads ? tr('在后台继续') : tr('完成') }}</AppButton></footer>
      </section>
    </ElDialog>
    <ElDialog class="resource-library-dialog" :model-value="Boolean(preview)" :title="preview?.name" width="min(850px, 92vw)" append-to-body destroy-on-close @close="preview = null"><video v-if="preview" class="library-preview-video" :src="mediaUrl(preview.url)" controls autoplay playsinline @error="error = tr('视频已删除或不可用，请重新选择')" /></ElDialog>
    <ElDialog class="resource-library-dialog" :model-value="Boolean(editFolder)" :title="tr(editFolder?.id ? '修改文件夹' : '新建文件夹')" width="420px" append-to-body @close="editFolder = null"><form v-if="editFolder" class="library-form" @submit.prevent="saveFolder"><label>{{ tr('文件夹名称') }}<input v-model="editFolder.name" required maxlength="100"></label><label>{{ tr('上级目录') }}<AppSelect :menu-z-index="3000" :model-value="String(editFolder.parent_id)" :options="parentFolderOptions" :ariaLabel="tr('上级目录')" :disabled="busy" @update:model-value="editFolder.parent_id = Number($event)" /></label><p v-if="error" role="alert" class="library-error">{{ error }}</p><AppButton type="submit" variant="primary" :disabled="busy">{{ tr('保存') }}</AppButton></form></ElDialog>
    <ElDialog class="resource-library-dialog" :model-value="Boolean(renameItem)" :title="tr('重命名视频')" width="420px" append-to-body @close="renameItem = null"><form class="library-form" @submit.prevent="saveRename"><label>{{ tr('视频名称') }}<input v-model="renameValue" required maxlength="255"></label><AppButton type="submit" :disabled="busy">{{ tr('保存') }}</AppButton></form></ElDialog>
    <ElDialog class="resource-library-dialog" v-model="moving" :title="tr('移动所选视频')" width="440px" append-to-body><form class="library-form" @submit.prevent="moveTo(targetFolder)"><label>{{ tr('目标文件夹') }}<AppSelect :menu-z-index="3000" :model-value="String(targetFolder)" :options="destinationFolderOptions" :ariaLabel="tr('目标文件夹')" :disabled="busy" @update:model-value="targetFolder = Number($event)" /></label><AppButton type="submit" :disabled="busy" variant="primary">{{ tr('移动到此处') }}</AppButton></form></ElDialog>
  </section>
</template>

<style scoped>
.resource-library { color: var(--app-text); min-width: 0; padding: 28px; }
.library-heading,.library-actions,.library-selection,.library-selection>div,.library-footer,.library-footer>div { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.library-heading { margin-bottom: 24px; flex-wrap: wrap; }.library-heading h1 { margin: 0 0 6px; font-size: 24px; }.library-heading p { margin: 0; color: var(--app-text-muted); font-size: 13px; }
.library-body { display: grid; grid-template-columns: 215px minmax(0,1fr); border: 1px solid var(--app-border); border-radius: 14px; background: var(--app-surface); min-height: 480px; }
.library-folders {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 4px;
  border-right: 1px solid var(--app-border);
  padding: 14px 10px;
  min-width: 0;
}
.library-folders button {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-height: 44px;
  padding: 10px;
  border: 0;
  border-radius: 8px;
  color: inherit;
  background: transparent;
  font: inherit;
  font-size: 14px;
  line-height: 20px;
  text-align: left;
  cursor: pointer;
}
.library-folders button:disabled { cursor: not-allowed; opacity: .5; }
.library-folders svg { flex-shrink: 0; }
.library-folders > button:hover:not(.active),
.library-folder-row:not(.active):hover { background: var(--app-surface-hover); }
.library-folders > button.active,
.library-folder-row.active { color: var(--app-accent); background: var(--app-accent-soft); }
.library-folder-row { display: flex; align-items: center; border-radius: 8px; min-width: 0; }
.library-folder-row > button { flex: 1; min-width: 0; }
.library-folder-row span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nested { margin-left: 18px; }
.folder-menu { position: relative; flex: 0 0 44px; }
.folder-menu summary {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  padding: 0;
  border-radius: 8px;
  color: var(--app-text-muted);
  list-style: none;
  cursor: pointer;
}
.folder-menu summary::-webkit-details-marker { display: none; }
.folder-menu summary::marker { content: ''; }
.folder-menu summary:hover,
.folder-menu[open] summary { color: var(--app-text); background: var(--app-surface-hover); }
.folder-menu summary:focus-visible { outline: 2px solid var(--app-accent); outline-offset: -2px; }
.folder-menu > div {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  width: 168px;
  z-index: 10;
  padding: 4px;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  color: var(--app-text);
  background: var(--app-surface);
  box-shadow: 0 4px 20px #0002;
}
.folder-menu > div button:hover:not(:disabled) { background: var(--app-surface-hover); }
.folder-menu > div button.danger { color: var(--app-danger, #c54d4d); }

.library-main { padding:20px; min-width:0; }.library-search { display:flex; align-items:center; gap:10px; padding:4px 4px 4px 12px; border:1px solid var(--app-border); border-radius:10px; }.library-search input { flex:1; width:0; border:0; background:transparent; color:inherit; padding:8px; }.library-selection { margin:16px 0; font-size:12px; flex-wrap:wrap; color:var(--app-text-muted); }.library-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:16px; }.library-card { border:1px solid var(--app-border); border-radius:12px; overflow:hidden; }.library-card.selected { border-color:var(--app-accent); box-shadow:0 0 0 1px var(--app-accent); }.library-cover { position:relative; aspect-ratio:16/9; background:var(--app-surface-muted); }.library-cover>button { display:grid; place-items:center; width:100%; height:100%; padding:0; border:0; cursor:pointer; color:var(--app-text-muted); background:transparent; }.library-cover img { width:100%; height:100%; object-fit:cover; }.library-cover input { position:absolute; top:10px; left:10px; width:20px; height:20px; accent-color:var(--app-accent); }.library-play { position:absolute; color:white; background:#0008; border-radius:50%; padding:8px; width:42px; height:42px; }.library-cover small { position:absolute; right:8px; bottom:8px; color:white; background:#000a; padding:2px 5px; border-radius:4px; }.library-card-info { padding:12px; }.library-card-info>strong,.library-card-info>small { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.library-card-info>strong { font-size:14px; }.library-card-info>small { font-size:11px; color:var(--app-text-muted); margin-top:6px; }.library-card-actions { display:flex; justify-content:flex-end; gap:4px; margin-top:8px; }.library-empty { display:grid; justify-items:center; gap:12px; padding:70px 12px; color:var(--app-text-muted); }.library-empty p { margin:0; font-size:13px; }.library-footer { margin-top:20px; flex-wrap:wrap; font-size:12px; }.library-error,.danger { color:var(--app-danger,#c54d4d); }.library-file-input { display:none; }.library-preview-video { display:block; width:100%; max-height:70vh; }.library-form { display:grid; gap:16px; }.library-form label { display:grid; gap:8px; }.library-form input { padding:10px; border:1px solid var(--app-border); background:var(--app-surface); border-radius:8px; color:var(--app-text); }.is-picker { padding:0; }button:focus-visible,input:focus-visible { outline:2px solid var(--app-accent); outline-offset:2px; }
.library-toolbar { display:flex; align-items:center; gap:10px; }.library-toolbar .library-search { flex:1; min-width:0; }.library-toolbar .library-actions { flex-shrink:0; gap:8px; }.is-picker .library-main { padding:14px; }.is-picker .library-selection { margin:12px 0; }
@media(max-width:700px) { .library-toolbar { flex-wrap:wrap; }.library-toolbar .library-search { flex-basis:100%; }.library-toolbar .library-actions { margin-left:auto; } }
.library-upload-summary { display:flex; align-items:center; gap:12px; padding:16px; margin-bottom:18px; border:1px solid var(--app-border); border-radius:12px; color:var(--app-accent); background:var(--app-accent-soft); }
.library-upload-summary>div { flex:1; min-width:0; }.library-upload-summary strong,.library-upload-summary small { display:block; }.library-upload-summary strong { font-size:14px; }.library-upload-summary small { color:var(--app-text-muted); font-size:12px; margin-top:4px; }
.library-upload-panel { display:grid; gap:16px; }.library-upload-panel header>strong { font-size:16px; }.library-upload-panel header>p { font-size:13px; color:var(--app-text-muted); line-height:1.6; margin:8px 0 0; }
.library-upload-job { border:1px solid var(--app-border); border-radius:12px; padding:16px; background:var(--app-surface-muted); }.upload-job-heading { display:flex; align-items:center; gap:10px; }.upload-job-heading>div { flex:1; min-width:0; }.upload-job-heading strong { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:14px; }.upload-job-heading small { display:block; color:var(--app-text-muted); margin-top:5px; font-size:12px; }.library-upload-job progress { display:block; width:100%; height:8px; margin:16px 0 12px; accent-color:var(--app-accent); }.upload-job-status { font-size:13px; margin:12px 0 0; }.is-done .upload-job-status,.is-done .upload-job-heading>svg:last-child { color:var(--app-success,#27805a); }.is-failed .upload-job-status,.is-failed .upload-job-heading>svg:last-child { color:var(--app-danger,#c54d4d); }.upload-job-actions,.library-upload-panel footer { display:flex; justify-content:flex-end; gap:8px; }.upload-job-actions:not(:empty) { margin-top:12px; }.upload-spinner { animation:upload-spin 1s linear infinite; flex-shrink:0; }@keyframes upload-spin { to { transform:rotate(360deg); } }@media(prefers-reduced-motion:reduce) { .upload-spinner { animation:none; } }
@media(max-width:700px) { .resource-library { padding:14px; }.is-picker { padding:0; }.library-body { grid-template-columns:1fr; }.library-folders { flex-direction:row; align-items:center; overflow:auto; border-right:0; border-bottom:1px solid var(--app-border); gap:8px; }.library-folders>button,.library-folder-row { flex:0 0 auto; max-width:200px; }.library-main { padding:12px; }.nested { margin-left:0; }.library-selection>div { flex-wrap:wrap; }.library-grid { grid-template-columns:repeat(auto-fill,minmax(145px,1fr)); } }
</style>
