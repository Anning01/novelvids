<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
import { Download, LoaderCircle, Upload } from 'lucide-vue-next'
import { api, mediaUrl } from '@/api'
import { tr } from '@/i18n'
import AppButton from '@/components/AppButton.vue'
import ShortDramaWorkspaceShell from '@/components/ShortDramaWorkspaceShell.vue'
import EditorWorkspace from '@/features/video-editor/EditorWorkspace.vue'
import { readShortDramaSettings } from '@/shared/shortDramaProject'
import { buildChapterVideoTimeline } from '@/shared/chapterVideoTimeline'
import { downloadVideoZip } from '@/shared/downloadZip'
import { notice } from '@/shared/notice'
import { stripChapterOrdinal } from '@/shared/chapterTitle'
import type { Chapter, NovelMeta } from '@/types'

const route = useRoute(), router = useRouter()
const projectId = computed(() => Number(route.params.projectId))
const project = ref<NovelMeta | null>(null), chapters = ref<Chapter[]>([])
const activeChapterId = computed(() => chapters.value.find(chapter => chapter.id === Number(route.query.chapter))?.id || chapters.value[0]?.id || 0)
const activeChapter = computed(() => chapters.value.find(chapter => chapter.id === activeChapterId.value))
const settings = computed(() => project.value ? readShortDramaSettings(project.value) : null)
const editor = ref<InstanceType<typeof EditorWorkspace> | null>(null)
const loading = ref(true), loadError = ref(''), downloading = ref(false), zipProgress = ref('')
const filename = computed(() => `${project.value?.name || tr('短剧项目')}-${activeChapter.value ? `${tr('第{p0}集', { p0: activeChapter.value.number })}-${stripChapterOrdinal(activeChapter.value.name)}` : tr('当前集')}`.replace(/[\/:*?"<>|]/g, '_'))
let zip: AbortController | null = null
let loadVersion = 0
async function load() {
  const version = ++loadVersion
  loading.value = true; loadError.value = ''; chapters.value = []; project.value = null
  try { const [novel, chapterResponse] = await Promise.all([api.novelMeta(projectId.value), api.chapters(projectId.value)]); if (version !== loadVersion) return; project.value = novel.data; chapters.value = chapterResponse.data.items }
  catch (reason) { if (version === loadVersion) loadError.value = reason instanceof Error ? reason.message : tr('视频工作区加载失败') }
  finally { if (version === loadVersion) loading.value = false }
}
async function flush() { return !editor.value?.dirty || await editor.value.flush() }
async function selectChapter(chapter: Chapter) { if (await flush()) await router.replace({ query: { ...route.query, chapter: String(chapter.id) } }) }
async function editScene(sceneId?: number) { if (await flush()) await router.push({ path: `/create/short-drama/storyboard/${projectId.value}`, query: { chapter: String(activeChapterId.value), ...(sceneId ? { scene: String(sceneId) } : {}) } }) }
async function downloadZip() {
  if (!activeChapterId.value || downloading.value) return
  downloading.value = true; zip = new AbortController(); zipProgress.value = tr('准备分镜素材')
  const chapter = activeChapterId.value, name = filename.value
  try {
    const response = await api.workbenchBootstrap(projectId.value, chapter)
    const items = buildChapterVideoTimeline(response.data.scenes, response.data.videos).filter(item => item.video?.url)
    if (!items.length) throw new Error(tr('当前没有可下载的视频'))
    const digits = Math.max(3, String(Math.max(...items.map(item => item.scene.sequence))).length)
    await downloadVideoZip(items.map(item => ({ url: mediaUrl(item.video!.url), filename: `${String(item.scene.sequence).padStart(digits, '0')}-${tr('分镜')}${item.scene.sequence}.mp4` })), `${name}-${tr('分镜视频')}.zip`, { signal: zip.signal, onProgress: (done, total) => { zipProgress.value = tr('正在打包 {p0}/{p1}', { p0: done, p1: total }) } })
  } catch (reason) { if (!(reason instanceof DOMException && reason.name === 'AbortError')) notice.error(reason instanceof Error ? reason.message : tr('下载失败')) }
  finally { downloading.value = false; zip = null }
}
function cancelZip() { zip?.abort() }
onBeforeRouteLeave(async () => { const result = await flush(); if (result) zip?.abort(); return result })
onBeforeRouteUpdate(flush)
watch(projectId, load, { immediate: true })
onBeforeUnmount(() => { ++loadVersion; zip?.abort() })
</script>
<template>
  <main class="video-editor-page">
    <ShortDramaWorkspaceShell :project-id="projectId" :project-name="project?.name || tr('短剧项目')" :aspect-ratio="settings?.aspectRatio || '16:9'" :resolution="settings?.resolution || '720p'" :style-name="settings?.style || ''" active-phase="video" :show-script-phase="project?.workflow_kind !== 'remake'" :chapters="chapters" :active-chapter-id="activeChapterId" :video-enabled="true" @select-chapter="selectChapter">
      <template #header-end><div class="video-header-actions"><AppButton variant="secondary" size="sm" :disabled="downloading || loading" :aria-label="tr('按序号打包下载分镜视频')" @click="downloadZip"><LoaderCircle v-if="downloading" :size="14" /><Download v-else :size="14" />{{ downloading ? zipProgress : tr('素材 ZIP') }}</AppButton><AppButton v-if="downloading" variant="ghost" size="sm" @click="cancelZip">{{ tr('取消') }}</AppButton><AppButton variant="primary" size="sm" :disabled="loading || !activeChapterId" @click="editor?.openExport()"><Upload :size="14" />{{ tr('导出成片') }}</AppButton></div></template>
      <div v-if="loading" class="editor-page-state"><LoaderCircle :size="28" />{{ tr('正在加载本集视频') }}</div>
      <div v-else-if="loadError" class="editor-page-state" role="alert"><p>{{ loadError }}</p><AppButton @click="load">{{ tr('重新加载') }}</AppButton></div>
      <EditorWorkspace v-else-if="activeChapterId" ref="editor" :project-id="projectId" :chapter-id="activeChapterId" :filename="filename" @edit-scene="editScene" />
      <div v-else class="editor-page-state">{{ tr('当前项目暂无章节') }}</div>
    </ShortDramaWorkspaceShell>
  </main>
</template>
<style scoped>
.video-editor-page{color:var(--app-text);background:var(--app-canvas);min-height:100vh}.video-header-actions{display:flex;flex-wrap:wrap;justify-content:flex-end;align-items:center;gap:6px}.video-header-actions :deep(.app-button){font-size:11px;min-height:32px;padding-inline:10px}
@media(max-width:700px){.video-header-actions{flex-wrap:nowrap}.video-editor-page :deep(.short-drama-header-end>.app-button){font-size:0;width:30px;min-width:30px;padding:0;gap:0}}
</style>
