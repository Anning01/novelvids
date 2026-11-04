<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Plus, Play, FolderOpen, RefreshCw } from 'lucide-vue-next'
import { mediaUrl } from '@/api'
import { tr } from '@/i18n'
import { useAuthStore } from '@/features/auth/authStore'
import { catalogApi, type CatalogResource } from './catalog'
import { libraryApi } from './api'
import type { ResourceFolder } from './types'
import type { EditorMedia } from '@/features/video-editor/types'

const props = defineProps<{ kind: 'video' | 'audio' | 'sticker'; readOnly: boolean }>()
const emit = defineEmits<{ select: [item: EditorMedia]; add: [item: EditorMedia] }>()
const auth = useAuthStore()
const items = ref<CatalogResource[]>([]), folders = ref<ResourceFolder[]>([])
const search = ref(''), keyword = ref(''), audioType = ref<'bgm' | 'sound'>('bgm')
const folder = ref(''), loading = ref(false), error = ref(''), folderError = ref('')
const page = ref(1), pages = ref(1), sentinel = ref<HTMLElement | null>(null)
const resourceKind = computed(() => props.kind === 'audio' ? audioType.value : props.kind)
const orderedFolders = computed(() => folders.value.filter(f => !f.parent_id).flatMap(parent => [
  { ...parent, label: parent.name },
  ...folders.value.filter(f => f.parent_id === parent.id).map(child => ({ ...child, label: `${parent.name} / ${child.name}` })),
]))
let sequence = 0, folderSequence = 0, failedPage = 1, disposed = false
let observer: IntersectionObserver | undefined
function convert(item: CatalogResource): EditorMedia {
  return { key: `library:${item.id}`, source: { kind: 'library', id: item.id }, kind: props.kind, library_kind: item.kind, name: item.name, url: item.url, poster: item.poster_url, duration: item.duration, width: item.width, height: item.height }
}
function observeMore() {
  observer?.disconnect()
  if (!disposed && sentinel.value && page.value < pages.value && !error.value) observer?.observe(sentinel.value)
}
async function load(next = 1) {
  const version = ++sequence
  loading.value = true; error.value = ''
  if (next === 1) { items.value = []; page.value = 1; pages.value = 1 }
  try {
    const response = await catalogApi.list({ kind: resourceKind.value, folder_id: folder.value === '' ? undefined : Number(folder.value), search: keyword.value, page: next, origin: 'all' })
    if (version !== sequence || disposed) return
    const rows = response.data.items.filter(i => i.catalog === 'media' && i.state === 'ready')
    items.value = next === 1 ? rows : [...items.value, ...rows.filter(row => !items.value.some(item => item.key === row.key))]
    page.value = next; pages.value = response.data.pagination.pages
  } catch (reason) {
    if (version === sequence && !disposed) { failedPage = next; error.value = reason instanceof Error ? reason.message : tr('资源库加载失败') }
  } finally {
    if (version === sequence && !disposed) {
      loading.value = false
      await nextTick()
      observeMore()
    }
  }
}
function loadMore() { if (!loading.value && !error.value && page.value < pages.value) void load(page.value + 1) }
async function loadFolders() {
  const version = ++folderSequence
  folderError.value = ''
  try {
    const response = await libraryApi.folders()
    if (version === folderSequence && !disposed) folders.value = response.data.filter(f => !f.deleting)
  } catch (reason) {
    if (version === folderSequence && !disposed) folderError.value = reason instanceof Error ? reason.message : tr('资源库加载失败')
  }
}
watch(() => auth.activeTeamId, () => { folder.value = ''; folders.value = []; void loadFolders() }, { immediate: true })
watch(() => [auth.activeTeamId, resourceKind.value], () => { search.value = ''; keyword.value = '' })
watch(() => [auth.activeTeamId, resourceKind.value, folder.value], () => { void load() }, { immediate: true })
function refreshOnFocus() { void loadFolders(); void load() }
onMounted(() => {
  if (typeof IntersectionObserver !== 'undefined') {
    observer = new IntersectionObserver(entries => { if (entries.some(entry => entry.isIntersecting)) loadMore() }, { rootMargin: '0px 0px 120px 0px' })
    observeMore()
  }
  window.addEventListener('focus', refreshOnFocus)
})
onBeforeUnmount(() => { disposed = true; ++sequence; ++folderSequence; observer?.disconnect(); window.removeEventListener('focus', refreshOnFocus) })
</script>
<template>
  <section class="team-resource-panel">
    <nav v-if="kind === 'audio'"><button :aria-pressed="audioType === 'bgm'" @click="audioType = 'bgm'">BGM</button><button :aria-pressed="audioType === 'sound'" @click="audioType = 'sound'">{{ tr('音效') }}</button></nav>
    <label class="team-resource-folder"><FolderOpen :size="14"/><select v-model="folder" :aria-label="tr('文件夹')"><option value="">{{ tr('全部文件夹') }}</option><option value="0">{{ tr('未分类') }}</option><option v-for="row in orderedFolders" :key="row.id" :value="String(row.id)">{{ row.label }}</option></select></label>
    <p v-if="folderError" role="alert">{{ folderError }} <button @click="loadFolders">{{ tr('重新加载') }}</button></p>
    <form @submit.prevent="keyword = search.trim(); load()"><input v-model="search" :placeholder="tr('搜索团队资源')" :aria-label="tr('搜索团队资源')"/><button type="submit" :aria-label="tr('搜索')"><RefreshCw :size="13"/></button></form>
    <article v-for="item in items" :key="item.key">
      <button class="team-resource-preview" :aria-label="tr('预览 {p0}', { p0: item.name })" @click="emit('select', convert(item))"><img v-if="item.poster_url || kind === 'sticker'" :src="mediaUrl(item.poster_url || item.url)" alt="" loading="lazy"/><Play v-else :size="18"/></button>
      <div><strong :title="item.name">{{ item.name }}</strong><small v-if="item.duration">{{ item.duration.toFixed(1) }}s</small><small v-else>{{ item.width }}×{{ item.height }}</small></div>
      <button :disabled="readOnly" :aria-label="tr('添加素材 {p0}', { p0: item.name })" @click="emit('add', convert(item))"><Plus :size="16"/></button>
    </article>
    <div ref="sentinel" class="team-resource-sentinel" aria-hidden="true"></div>
    <p v-if="loading" role="status">{{ tr('正在加载资源…') }}</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <div v-if="!loading && !items.length && !error" class="team-resource-empty"><FolderOpen :size="25"/><span>{{ tr('团队资源库暂无此类素材') }}</span></div>
    <button v-if="error" @click="load(failedPage)">{{ tr('重新加载') }}</button>
    <button v-if="page < pages && !error" :disabled="loading" @click="loadMore">{{ tr('加载更多') }}</button>
    <RouterLink target="_blank" rel="noopener" :to="{ path: '/resource-library', query: { kind: resourceKind, search: keyword || undefined, folder: folder || undefined } }">{{ tr('管理团队资源') }}</RouterLink>
  </section>
</template>
<style scoped>
.team-resource-panel{display:grid;gap:8px;min-width:0;color:var(--app-text);font-size:11px}nav{display:flex;gap:12px}button{border:0;background:transparent;color:inherit;cursor:pointer;font:inherit;padding:5px}button:disabled{opacity:.4;cursor:not-allowed}button:hover:not(:disabled){background:var(--app-surface-hover)}button[aria-pressed=true]{color:var(--app-accent);border-bottom:1px solid var(--app-accent)}form{display:flex;align-items:center;border:1px solid var(--app-border);border-radius:5px;overflow:hidden}form:focus-within{outline:2px solid var(--app-accent);outline-offset:2px}form input{min-width:0;width:100%;height:28px;border:0!important;background:var(--app-surface)!important;color:var(--app-text);padding:0 8px}.team-resource-folder{display:flex;align-items:center;gap:6px;min-width:0;color:var(--app-text-secondary)}select{flex:1;min-width:0;width:100%;height:28px;color:var(--app-text);background:var(--app-surface-muted);border:1px solid var(--app-border);border-radius:5px}article{display:flex;align-items:center;gap:8px;min-width:0}article>button:last-child{flex-shrink:0}.team-resource-preview{width:36px;height:36px;padding:0;background:var(--app-surface-muted);border:1px solid var(--app-border);border-radius:5px;flex-shrink:0;overflow:hidden;display:grid;place-items:center;color:var(--app-accent)}img{width:100%;height:100%;object-fit:contain}article>div{min-width:0;flex:1}strong{display:block;font-size:11px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}small{display:block;color:var(--app-text-secondary);font-size:10px;margin-top:3px}.team-resource-empty{display:flex;align-items:center;justify-content:center;flex-direction:column;gap:8px;min-height:90px;color:var(--app-text-secondary)}.team-resource-sentinel{height:1px}a{font-size:10px;color:var(--app-accent);text-decoration:none;margin-top:4px}p{margin:0;font-size:11px;color:var(--app-text-secondary)}[role=alert]{color:var(--app-danger)}
</style>
