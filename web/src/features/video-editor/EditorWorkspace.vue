<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Download, GripHorizontal, LoaderCircle, Maximize2, Pause, Play, Save, SkipBack, SkipForward, Upload, Volume2, VolumeX, X, SlidersHorizontal } from 'lucide-vue-next'
import { API_BASE, authHeaders } from '@/api'
import { tr } from '@/i18n'
import { notice } from '@/shared/notice'
import { downloadFile } from '@/shared/downloadFile'
import { useAuthStore } from '@/features/auth/authStore'
import { catalogApi } from '@/features/resource-library/catalog'
import ResourceLibraryPicker from '@/features/resource-library/ResourceLibraryPicker.vue'
import AppSelect from '@/components/AppSelect.vue'
import type { VideoResource } from '@/features/resource-library/types'
import EditorLibrary from './EditorLibrary.vue'
import EditorInspector from './EditorInspector.vue'
import EditorPreview from './EditorPreview.vue'
import EditorTimeline from './EditorTimeline.vue'
import { editorApi } from './api'
import { useEditorDraft } from './useEditorDraft'
import { activeAt, addMedia, addSubtitle, changeClip, cloneDocument, duplicateClip, frameTime, moveClip, orderedVideos, parseSrt, sourceKey, splitClip, totalDuration, trimClip } from './model'
import type { ClipKind, ClipPatch, EditDocument, EditorCapabilities, EditorMedia, EditorExport } from './types'
import './editor.css'

const props = defineProps<{ projectId: number; chapterId: number; filename: string }>()
const emit = defineEmits<{ editScene: [sceneId?: number] }>()
const auth = useAuthStore()
const draft = useEditorDraft(() => `${auth.user?.id || 'anonymous'}:${auth.activeTeamId || 0}:${props.projectId}`)
const { document: editDocument, media, selectedId, selected, loading, saving, error, saveError, conflict, dirty, recovery, undoStack, redoStack } = draft
const readOnly = computed(() => auth.enabled === true && !['admin', 'creator', 'super'].includes(auth.role || ''))
const time = ref(0), playing = ref(false), muted = ref(false), inspectorOpen = ref(false), libraryOpen = ref(false)
const browsing = ref<EditorMedia | null>(null), browseTime = ref(0)
const preview = ref<InstanceType<typeof EditorPreview> | null>(null), timeline = ref<InstanceType<typeof EditorTimeline> | null>(null), previewStage = ref<HTMLElement | null>(null)
const uploadInput = ref<HTMLInputElement | null>(null), srtInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false), uploadProgress = ref(0), capabilities = ref<EditorCapabilities | null>(null)
const exports = ref<EditorExport[]>([]), exportOpen = ref(false), exporting = ref(false), exportError = ref('')
const timelineHeight = ref(310), downloading = ref(false)
let uploadKind: Exclude<ClipKind, 'subtitle'> = 'video', scope = 0, disposed = false, polling: ReturnType<typeof setTimeout> | undefined
let resizeCleanup: (() => void) | null = null
let exportFocus: HTMLElement | null = null
const duration = computed(() => editDocument.value ? totalDuration(editDocument.value) : 0)
const selectedMedia = computed(() => selected.value && 'source' in selected.value ? media.value.find(item => item.key === sourceKey(selected.value!.type !== 'subtitle' ? selected.value!.source : { kind: 'missing', id: 1 })) : undefined)
const activeVideo = computed(() => editDocument.value ? orderedVideos(editDocument.value).find(clip => activeAt(clip, time.value)) : null)
const previewDocument = computed<EditDocument | null>(() => {
  const doc = editDocument.value, item = browsing.value
  return doc && item ? addMedia({ ...doc, clips: [] }, item, 0, '')[0] : doc
})
const previewTime = computed({ get: () => browsing.value ? browseTime.value : time.value, set: value => { if (browsing.value) browseTime.value = value; else time.value = value } })
const previewDuration = computed(() => previewDocument.value ? totalDuration(previewDocument.value) : 0)
const ratio = computed(() => editDocument.value ? `${editDocument.value.width}:${editDocument.value.height}` : '')
const aspect = computed(() => { const doc = editDocument.value; if (!doc) return '16:9'; const value = doc.width / doc.height; return ['16:9', '9:16', '1:1', '4:3', '3:4', '21:9'].find(key => { const [w, h] = key.split(':').map(Number); return Math.abs(w! / h! - value) < .01 }) || 'custom' })
const pendingExport = computed(() => exports.value.find(row => [1, 2, 6].includes(row.status)))
const missingClips = computed(() => editDocument.value?.clips.filter(clip => 'source' in clip && (!media.value.find(item => item.key === sourceKey(clip.source))?.url || media.value.find(item => item.key === sourceKey(clip.source))?.missing)) || [])
const status = computed(() => saving.value ? tr('正在保存') : dirty.value ? tr('有未保存修改') : tr('已保存'))
function showError(reason: unknown) { notice.error(reason instanceof Error ? reason.message : tr('剪辑操作失败')) }
function action(fn: () => EditDocument | [EditDocument, string]) {
  if (readOnly.value || !editDocument.value) return
  playing.value = false; browsing.value = null
  try { const result = fn(); if (Array.isArray(result)) draft.commit(result[0], result[1]); else draft.commit(result) }
  catch (reason) { showError(reason) }
}
function select(id: string, seek = true) {
  browsing.value = null
  selectedId.value = id
  const clip = editDocument.value?.clips.find(item => item.id === id)
  if (seek && clip && !activeAt(clip, time.value)) void seekTo(clip.start)
  if (innerWidth <= 1000) inspectorOpen.value = true
}
async function seekTo(value: number) { browsing.value = null; time.value = Math.min(duration.value, Math.max(0, value)); await nextTick(); await preview.value?.seek() }
async function seekPreview(value: number) { previewTime.value = Math.min(previewDuration.value, Math.max(0, value)); await nextTick(); await preview.value?.seek() }
function change(patch: ClipPatch) { if (selected.value && editDocument.value) action(() => changeClip(editDocument.value!, selected.value!.id, patch, selectedMedia.value)) }
function trim(trimIn: number, trimOut: number, speed: number) { if (selected.value && selectedMedia.value) action(() => trimClip(editDocument.value!, selected.value!.id, trimIn, trimOut, speed, selectedMedia.value!)) }
function move(id: string, start: number) { action(() => moveClip(editDocument.value!, id, start)) }
function remove() { if (!selected.value) return; action(() => ({ ...cloneDocument(editDocument.value!), clips: editDocument.value!.clips.filter(c => c.id !== selectedId.value) })) ; selectedId.value = editDocument.value?.clips[0]?.id || '' }
function duplicate() { action(() => duplicateClip(editDocument.value!, selectedId.value)) }
function split() { action(() => splitClip(editDocument.value!, selectedId.value, time.value)) }
function edge(id: string, side: 'left' | 'right', delta: number) {
  const clip = editDocument.value?.clips.find(item => item.id === id)
  if (!clip || !editDocument.value) return
  if (side === 'right') {
    const duration = frameTime(clip.duration + delta, editDocument.value.fps)
    const item = 'source' in clip ? media.value.find(m => m.key === sourceKey(clip.source)) : undefined
    action(() => changeClip(editDocument.value!, id, { duration }, item)); return
  }
  const start = frameTime(Math.max(0, clip.start + delta), editDocument.value.fps), actual = start - clip.start
  const patch: ClipPatch = { start, duration: clip.duration - actual }
  if (clip.type === 'video' || clip.type === 'audio') patch.trim_in = clip.trim_in + actual * (clip.type === 'video' ? clip.speed : 1)
  action(() => changeClip(editDocument.value!, id, patch, 'source' in clip ? media.value.find(m => m.key === sourceKey(clip.source)) : undefined))
}
function insert(item: EditorMedia) { action(() => addMedia(editDocument.value!, item, time.value, selectedId.value)) }
function chooseMedia(item: EditorMedia) {
  draft.addMedia(item)
  const clip = editDocument.value?.clips.find(c => 'source' in c && sourceKey(c.source) === item.key)
  if (clip) select(clip.id)
  else { playing.value = false; browsing.value = item; browseTime.value = 0 }
}
function subtitle() { action(() => addSubtitle(editDocument.value!, time.value)) }
function requestUpload(kind: Exclude<ClipKind, 'subtitle'>) {
  if (uploading.value || readOnly.value) return
  uploadKind = kind
  if (uploadInput.value && capabilities.value) { uploadInput.value.accept = capabilities.value.formats[kind]?.map(ext => '.' + ext).join(',') || ''; uploadInput.value.click() }
}
function add(kind: ClipKind) { if (kind === 'subtitle') subtitle(); else requestUpload(kind) }
async function uploaded(event: Event) {
  const element = event.target as HTMLInputElement, files = Array.from(element.files || []), version = scope, chapter = props.chapterId, kind = uploadKind
  if (!files.length || uploading.value || readOnly.value) return
  uploading.value = true
  try {
    for (const file of files) {
      if (file.size > (capabilities.value?.max_size_mb || 0) * 1024 * 1024) throw new Error(tr('素材大小超过服务端限制'))
      uploadProgress.value = 0
      const item = await editorApi.upload(chapter, file, kind, percent => { if (version === scope) uploadProgress.value = percent })
      if (version !== scope || disposed) return
      draft.addMedia(item)
    }
    notice.success(tr('素材已导入，点击加号添加到时间线'))
  } catch (reason) { if (version === scope) showError(reason) }
  finally { if (version === scope) uploading.value = false; element.value = '' }
}
async function srtChanged(event: Event) {
  const element = event.target as HTMLInputElement, file = element.files?.[0], version = scope
  if (!file || !editDocument.value) return
  try {
    if (file.size > 1024 * 1024) throw new Error(tr('字幕文件过大'))
    const text = await file.text(); if (version !== scope || disposed) return
    action(() => ({ ...cloneDocument(editDocument.value!), clips: [...editDocument.value!.clips, ...parseSrt(text, editDocument.value!)] }))
  } catch (reason) { showError(reason) }
  finally { element.value = '' }
}
async function publishMedia(item: EditorMedia) {
  if (readOnly.value || item.source.kind !== 'asset') return
  try { await catalogApi.publish('editor', item.source.id, 0, item.kind === 'audio' ? 'bgm' : item.kind); notice.success(tr('已存入团队资源库')) } catch(reason) { showError(reason) }
}
async function libraryChosen(items: Pick<VideoResource, 'id'>[]) {
  const version = scope, chapter = props.chapterId
  try { for (const item of items) { const response = await editorApi.library(chapter, item.id); if (version !== scope || disposed) return; draft.addMedia(response.data); insert(response.data) } libraryOpen.value = false }
  catch (reason) { if (version === scope) showError(reason) }
}
function dimensions(value: string, shortSide?: number) {
  const doc = editDocument.value; if (!doc || readOnly.value) return
  const [a, b] = value.split(':').map(Number)
  const side = shortSide || Math.min(doc.width, doc.height)
  action(() => ({ ...cloneDocument(doc), width: Math.round((a! >= b! ? side * a! / b! : side) / 2) * 2, height: Math.round((a! >= b! ? side : side * b! / a!) / 2) * 2 }))
}
function resized(event: PointerEvent) {
  const y = event.clientY, height = timelineHeight.value
  const move = (e: PointerEvent) => timelineHeight.value = Math.max(230, Math.min(innerHeight * .6, height + y - e.clientY))
  resizeCleanup?.(); const stop = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stop); resizeCleanup = null }
  resizeCleanup = stop; window.addEventListener('pointermove', move); window.addEventListener('pointerup', stop, { once: true })
}
async function load() {
  const version = ++scope; playing.value = false; time.value = 0; browsing.value = null; uploading.value = false; exportError.value = ''; clearTimeout(polling)
  await draft.load(props.chapterId)
  if (version !== scope || disposed) return
  try { capabilities.value = (await editorApi.capabilities()).data } catch (reason) { if (version === scope) showError(reason) }
  await refreshExports(version)
}
async function refreshExports(version = scope) {
  clearTimeout(polling)
  try {
    const response = await editorApi.history(props.chapterId)
    if (version !== scope || disposed) return
    exports.value = response.data
    exportError.value = ''
  } catch (reason) { if (version === scope) exportError.value = reason instanceof Error ? reason.message : tr('导出状态读取失败') }
  finally { if (version === scope && !disposed && (pendingExport.value || exportError.value)) polling = setTimeout(() => { void refreshExports(version) }, 2500) }
}
async function beginExport() {
  if (readOnly.value || exporting.value || !editDocument.value) return
  const version = scope
  exporting.value = true; exportError.value = ''
  try {
    if (!await draft.save()) throw new Error(saveError.value || tr('请先保存当前剪辑草稿后再导出'))
    if (version !== scope || disposed) return
    const result = await editorApi.export(props.chapterId, draft.revision.value)
    if (version !== scope || disposed) return
    exports.value = [result.data, ...exports.value.filter(item => item.id !== result.data.id)]
    void refreshExports(version)
  } catch (reason) { if (version === scope) exportError.value = reason instanceof Error ? reason.message : tr('成片导出失败') }
  finally { if (version === scope) exporting.value = false }
}
async function download(row: EditorExport) {
  if (!row.url || downloading.value) return
  downloading.value = true
  try { await downloadFile(row.url.replace('/api', API_BASE), `${props.filename}-v${row.revision}.mp4`, authHeaders()) }
  catch (reason) { showError(reason) }
  finally { downloading.value = false }
}
async function cancelExport(row: EditorExport) { try { await editorApi.cancel(row.task_id); await refreshExports() } catch (reason) { showError(reason) } }
async function replaceSource() {
  if (selected.value?.type !== 'video' || !editDocument.value) return
  const current = selected.value, version = scope
  const source = media.value.find(item => item.key === sourceKey(current.source))
  const sceneId = source?.scene_id || (current.source.kind === 'missing' ? current.source.id : null)
  if (!sceneId) return notice.info(tr('该素材不来自本集分镜'))
  try {
    const result = await editorApi.get(props.chapterId)
    if (version !== scope || disposed) return
    const updated = result.data.media.find(item => item.scene_id === sceneId && item.source.kind === 'video')
    if (!updated) throw new Error(tr('此分镜尚无可用视频'))
    draft.addMedia(updated)
    action(() => changeClip(editDocument.value!, current.id, { source: updated.source }, updated))
  } catch (reason) { showError(reason) }
}
function editSource() { const scene = selectedMedia.value?.scene_id; if (scene) emit('editScene', scene); else notice.info(tr('该素材不来自本集分镜')) }
function toggle() { if (!editDocument.value) return; if (previewTime.value >= previewDuration.value) previewTime.value = 0; playing.value = !playing.value }
function adjacent(delta: number) { const videos = editDocument.value ? orderedVideos(editDocument.value) : []; const i = videos.findIndex(clip => activeAt(clip, time.value)); const next = videos[Math.min(videos.length - 1, Math.max(0, i + delta))]; if (next) void seekTo(next.start) }
function keys(event: KeyboardEvent) {
  const target = event.target instanceof HTMLElement ? event.target : null
  if (target?.closest('input,textarea,select,[contenteditable]')) return
  if (!readOnly.value && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
    event.preventDefault(); playing.value = false; event.shiftKey ? draft.redo() : draft.undo(); return
  }
  if (target?.closest('button,[role=separator]')) return
  if (event.code === 'Space') { event.preventDefault(); toggle() }
  if (readOnly.value) return
  if (event.key === 'Delete') { event.preventDefault(); remove() }
}
function modalKeys(event: KeyboardEvent) {
  if (event.key !== 'Tab' || !(event.currentTarget instanceof HTMLElement)) return
  const targets = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]'))
  const first = targets[0], last = targets.at(-1)
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
watch(exportOpen, async value => {
  if (value) { exportFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null; await nextTick(); document.querySelector<HTMLElement>('.editor-export-dialog button')?.focus() }
  else { exportFocus?.focus(); exportFocus = null }
})
watch(() => [props.projectId, props.chapterId, auth.activeTeamId], () => { if (props.chapterId) void load() }, { immediate: true })
watch(time, () => { if (playing.value) timeline.value?.reveal() })
watch(duration, value => { time.value = Math.min(time.value, value) })
onMounted(() => window.addEventListener('keydown', keys))
onBeforeUnmount(() => { disposed = true; ++scope; clearTimeout(polling); resizeCleanup?.(); window.removeEventListener('keydown', keys) })
defineExpose({ flush: draft.save, openExport: () => { exportOpen.value = true }, dirty })
function format(value: number) { return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(Math.floor(value % 60)).padStart(2, '0')}` }
</script>

<template>
  <section class="editor-workspace" :style="{ '--editor-timeline-height': `${timelineHeight}px` }">
    <div v-if="loading" class="editor-page-state" role="status"><LoaderCircle class="is-spinning" :size="28" />{{ tr('正在读取剪辑草稿') }}</div>
    <div v-else-if="error" class="editor-page-state" role="alert"><p>{{ error }}</p><button class="editor-btn secondary" @click="load">{{ tr('重新加载') }}</button></div>
    <template v-else-if="editDocument">
      <div class="editor-statusbar"><span>{{ readOnly ? tr('只读预览') : status }}</span><div class="editor-canvas-settings"><label>{{ tr('比例') }}<AppSelect :model-value="aspect" :options="[...(aspect==='custom'?[{value:'custom',label:ratio}]:[]),...(['16:9','9:16','1:1','4:3','3:4','21:9'])]" :ariaLabel="tr('比例')" :disabled="readOnly" density="compact" @update:model-value="dimensions" /></label><label>{{ tr('画布尺寸') }}<AppSelect :model-value="String(Math.min(editDocument.width,editDocument.height))" :options="[...(!capabilities?.resolutions.includes(Math.min(editDocument.width,editDocument.height))?[Math.min(editDocument.width,editDocument.height)]:[]),...(capabilities?.resolutions||[])].map(value=>({value:String(value),label:`${value}P`}))" :ariaLabel="tr('画布尺寸')" :disabled="readOnly" density="compact" @update:model-value="dimensions(`${editDocument.width}:${editDocument.height}`,Number($event))" /></label><label>FPS<AppSelect :model-value="String(editDocument.fps)" :options="(capabilities?.fps||[24]).map(value=>({value:String(value),label:String(value)}))" ariaLabel="FPS" :disabled="readOnly" density="compact" @update:model-value="action(()=>({...cloneDocument(editDocument!),fps:Number($event) as EditDocument['fps']}))" /></label><button class="editor-icon-btn" :disabled="readOnly || saving || conflict" :aria-label="tr('保存剪辑草稿')" @click="draft.save"><Save :size="15" /></button></div></div>
      <div v-if="saveError || recovery" class="editor-save-alert" role="alert"><span>{{ saveError || tr('发现尚未保存的本地剪辑草稿') }}</span><template v-if="recovery"><button @click="draft.recoverLocal">{{ tr('恢复本地修改') }}</button><button @click="draft.ignoreRecovery">{{ tr('使用已保存版本') }}</button></template><template v-else><button v-if="conflict" @click="load">{{ tr('重新读取并核对') }}</button><button v-else @click="draft.save">{{ tr('重试保存') }}</button></template></div>
      <div class="editor-editing-row">
        <EditorLibrary :media="media" :selected-key="selectedMedia?.key" :read-only="readOnly" :busy="uploading" :progress="uploadProgress" @select="chooseMedia" @add="insert" @upload="requestUpload" @subtitle="subtitle" @srt="srtInput?.click()" @library="libraryOpen = true" @library-add="item => libraryChosen([{ id: item.source.id }])" @publish="publishMedia" />
        <section class="editor-preview-panel"><header class="editor-panel-heading video-stage-header"><h2>{{ browsing ? tr('素材预览') : tr('本集预览') }}</h2><span>{{ browsing?.name || activeVideo?.name }}</span><button class="editor-icon-btn" :aria-label="tr('全屏预览')" @click="previewStage?.requestFullscreen()"><Maximize2 :size="15" /></button></header><div ref="previewStage" class="editor-preview-area video-stage"><EditorPreview ref="preview" :document="previewDocument!" :media="media" v-model:time="previewTime" v-model:playing="playing" :muted="muted" :selected-id="selectedId" @select="id => select(id, false)" /></div><footer class="editor-transport"><span>{{ format(previewTime) }} <small>/ {{ format(previewDuration) }}</small></span><div><button class="editor-icon-btn" :aria-label="tr('上一个分镜')" @click="adjacent(-1)"><SkipBack :size="17" /></button><button class="editor-icon-btn" :aria-label="playing ? tr('暂停') : tr('播放')" @click="toggle"><Pause v-if="playing" :size="18" /><Play v-else :size="18" /></button><button class="editor-icon-btn" :aria-label="tr('下一个分镜')" @click="adjacent(1)"><SkipForward :size="17" /></button></div><div><button class="editor-icon-btn" :aria-label="muted ? tr('取消静音') : tr('静音')" @click="muted = !muted"><VolumeX v-if="muted" :size="16" /><Volume2 v-else :size="16" /></button><button class="editor-btn secondary editor-mobile-only" @click="inspectorOpen = true"><SlidersHorizontal :size="14" />{{ tr('属性') }}</button></div></footer><div class="editor-playback-seek-row"><input class="editor-playback-seek" type="range" min="0" :max="previewDuration || 1" step=".04" :value="previewTime" :aria-label="tr('本集视频播放进度')" @input="seekPreview(Number(($event.target as HTMLInputElement).value))" /></div></section>
        <EditorInspector :clip="browsing ? null : selected" :browsing="browsing" :media="selectedMedia" :open="inspectorOpen" :read-only="readOnly" @close="inspectorOpen = false" @change="change" @trim="trim" @remove="remove" @duplicate="duplicate" @move="delta => selected && move(selected.id, selected.start + delta)" @source="editSource" @replace="replaceSource" />
      </div>
      <div class="editor-timeline-resizer" role="separator" tabindex="0" :aria-label="tr('调整时间线高度')" aria-orientation="horizontal" @pointerdown="resized" @keydown.up.prevent="timelineHeight = Math.min(480, timelineHeight + 20)" @keydown.down.prevent="timelineHeight = Math.max(230, timelineHeight - 20)"><GripHorizontal :size="15" /></div>
      <EditorTimeline ref="timeline" :document="editDocument" :media="media" :time="time" :selected-id="selectedId" :read-only="readOnly" :can-undo="!!undoStack.length" :can-redo="!!redoStack.length" @select="select" @seek="seekTo" @move="move" @edge="edge" @add="add" @split="split" @remove="remove" @duplicate="duplicate" @undo="playing = false; draft.undo()" @redo="playing = false; draft.redo()" />
    </template>
    <input ref="uploadInput" type="file" multiple class="editor-hidden" @change="uploaded" /><input ref="srtInput" type="file" accept=".srt" class="editor-hidden" @change="srtChanged" />
    <ResourceLibraryPicker :open="libraryOpen" @close="libraryOpen = false" @choose="libraryChosen" />
    <Teleport to="body"><div v-if="exportOpen" class="editor-modal-backdrop" @click.self="exportOpen = false"><section class="editor-export-dialog" role="dialog" aria-modal="true" :aria-label="tr('导出编辑成片')" @keydown.esc="exportOpen = false" @keydown="modalKeys"><header><h2>{{ tr('导出编辑成片') }}</h2><button class="editor-icon-btn" :aria-label="tr('关闭')" @click="exportOpen = false"><X :size="18" /></button></header><p>{{ editDocument?.width }}×{{ editDocument?.height }} · {{ editDocument?.fps }}fps · {{ format(duration) }}</p><p class="editor-panel-note">{{ tr('按照已保存的时间线合成视频、BGM、字幕和贴纸；不调用生成模型。') }}</p><p v-if="missingClips.length" role="alert" class="danger">{{ tr('仍有 {p0} 个片段缺少素材，需先补全或从时间线移除', { p0: missingClips.length }) }}</p><p v-if="exportError" role="alert" class="danger">{{ exportError }}</p><button class="editor-btn primary full-width" :disabled="readOnly || !!missingClips.length || exporting || !!pendingExport || !duration" @click="beginExport"><LoaderCircle v-if="exporting || pendingExport" :size="15" class="is-spinning" /><Upload v-else :size="15" />{{ pendingExport ? tr('导出中 {p0}%', { p0: pendingExport.progress }) : tr('开始导出') }}</button><div class="editor-export-history"><article v-for="row in exports" :key="row.id"><div><strong>{{ tr('剪辑版本 {p0}', { p0: row.revision }) }}</strong><small>{{ row.status === 3 ? tr('已完成') : [1,2,6].includes(row.status) ? tr('处理中 {p0}%', { p0: row.progress }) : row.status === 5 ? tr('已取消') : row.error || tr('导出失败') }}</small></div><button v-if="row.status === 3 && row.url" class="editor-btn secondary" :disabled="downloading" @click="download(row)"><Download :size="14" />{{ tr('下载') }}</button><button v-else-if="[1,2,6].includes(row.status)" class="editor-link" :disabled="readOnly" @click="cancelExport(row)">{{ tr('取消') }}</button></article></div></section></div></Teleport>
  </section>
</template>
