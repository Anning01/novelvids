<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowRight,
  CheckCircle2,
  ChevronRight,
  Film,
  FolderUp,
  History,
  Monitor,
  RefreshCcw,
  Sparkles,
  UploadCloud,
  X,
} from 'lucide-vue-next'
import { api } from '@/api'
import AppButton from '@/components/AppButton.vue'
import AppSelect from '@/components/AppSelect.vue'
import CreationConfigBar from '@/components/CreationConfigBar.vue'
import CreationEntryShell from '@/components/CreationEntryShell.vue'
import { prepareFolderBatch, type FolderVideoEntry } from '@/features/remake/folderEpisodes'
import type { RemakeCapabilities, RemakeHistoryEpisode, RemakeHistoryProject, RemakeUpload } from '@/types'

type UploadState = 'empty' | 'uploading' | 'ready' | 'failed'
type SourceMode = 'single_upload' | 'folder_upload' | 'history'

const router = useRouter()
const capabilities = ref<RemakeCapabilities | null>(null)
const loadingCapabilities = ref(true)
const capabilityError = ref('')
const projectName = ref('')
const aspectRatio = ref('')
const resolution = ref('')
const styleKey = ref('auto')
const customStylePrompt = ref('')
const selectedFile = ref<File | null>(null)
const stagedUpload = ref<RemakeUpload | null>(null)
const uploadState = ref<UploadState>('empty')
const errorMessage = ref('')
const creating = ref(false)
const projectCommitted = ref(false)
const idempotencyKey = ref(createIdempotencyKey())
const sourceMode = ref<SourceMode>('single_upload')
const historyProjects = ref<RemakeHistoryProject[]>([])
const historyEpisodes = ref<RemakeHistoryEpisode[]>([])
const selectedHistoryProjectId = ref<number | null>(null)
const selectedHistoryChapterId = ref<number | null>(null)
const loadingHistory = ref(false)
const loadingEpisodes = ref(false)
const folderEntries = ref<FolderVideoEntry[]>([])
const missingFolderEpisodes = ref<number[]>([])
const gapConfirmed = ref(false)
const uploadingFolder = ref(false)

const customStyleSelected = computed(() => styleKey.value === 'custom')
const visualStyleOptions = computed(() => [
  { value: 'auto', label: 'AI 识别风格' },
  ...(capabilities.value?.styles ?? [])
    .filter(style => style.key !== 'auto')
    .map(style => ({
      value: style.key,
      label: style.label,
      image: `/style-thumbnails/${style.key}.png`,
    })),
  { value: 'custom', label: '自定义风格', separator: true },
])
const sourceReady = computed(() => {
  if (sourceMode.value === 'single_upload') {
    return uploadState.value === 'ready' && Boolean(stagedUpload.value)
  }
  if (sourceMode.value === 'history') {
    return selectedHistoryChapterId.value !== null
  }
  const uploadable = folderEntries.value.filter(entry => entry.state !== 'ignored')
  return uploadable.length > 0
    && uploadable.every(entry => entry.state === 'ready')
    && (missingFolderEpisodes.value.length === 0 || gapConfirmed.value)
})
const canSubmit = computed(() => (
  Boolean(capabilities.value)
  && sourceReady.value
  && Boolean(projectName.value.trim())
  && Boolean(aspectRatio.value)
  && Boolean(resolution.value)
  && Boolean(styleKey.value)
  && (!customStyleSelected.value || Boolean(customStylePrompt.value.trim()))
  && !creating.value
))
const fileMeta = computed(() => {
  if (!stagedUpload.value) return ''
  const size = stagedUpload.value.size_bytes / 1024 / 1024
  return `${size >= 1 ? size.toFixed(1) : '< 1'} MB · ${formatDuration(stagedUpload.value.duration_seconds)} · ${stagedUpload.value.width}×${stagedUpload.value.height}`
})

function createIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, character => {
    const random = Math.floor(Math.random() * 16)
    const value = character === 'x' ? random : (random & 0x3) | 0x8
    return value.toString(16)
  })
}

function formatDuration(seconds: number): string {
  const rounded = Math.round(seconds)
  return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, '0')}`
}

function formatFileSize(bytes: number): string {
  const size = bytes / 1024 / 1024
  return `${size >= 1 ? size.toFixed(1) : '< 1'} MB`
}

function folderStateLabel(entry: FolderVideoEntry): string {
  return {
    pending: '待上传',
    uploading: `上传中 ${entry.progress}%`,
    ready: '已就绪',
    failed: '上传失败',
    invalid: '需处理',
    ignored: '已忽略',
  }[entry.state]
}

function setDefaults(data: RemakeCapabilities) {
  aspectRatio.value = data.aspect_ratios.includes('9:16') ? '9:16' : (data.aspect_ratios[0] ?? '')
  resolution.value = data.resolutions.includes('720p') ? '720p' : (data.resolutions[0] ?? '')
  styleKey.value = 'auto'
}

async function loadCapabilities() {
  loadingCapabilities.value = true
  capabilityError.value = ''
  try {
    const response = await api.remakeCapabilities()
    capabilities.value = response.data
    setDefaults(response.data)
  } catch (error) {
    capabilityError.value = (error as Error).message || '重制能力加载失败'
  } finally {
    loadingCapabilities.value = false
  }
}

function validateFile(file: File): string {
  const allowed = capabilities.value?.media.extensions ?? ['mp4', 'mov']
  const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
  if (!allowed.includes(extension)) return '仅支持 MP4 或 MOV 格式的视频'
  const maxBytes = capabilities.value?.media.max_bytes ?? 500 * 1024 * 1024
  if (file.size > maxBytes) return '单视频不能超过 500 MB'
  if (file.size <= 0) return '视频文件不能为空'
  return ''
}

async function releaseCurrentUpload() {
  const token = stagedUpload.value?.upload_token
  stagedUpload.value = null
  if (!token || projectCommitted.value) return
  await api.releaseRemakeUpload(token).catch(() => undefined)
}

async function releaseFolderUploads() {
  if (projectCommitted.value) return
  const tokens = folderEntries.value
    .map(entry => entry.uploadToken)
    .filter((token): token is string => Boolean(token))
  await Promise.all(tokens.map(token => api.releaseRemakeUpload(token).catch(() => undefined)))
  folderEntries.value.forEach(entry => { entry.uploadToken = undefined })
}

async function uploadFile(file: File) {
  errorMessage.value = ''
  const validationError = validateFile(file)
  if (validationError) {
    errorMessage.value = validationError
    uploadState.value = 'failed'
    return
  }
  await releaseCurrentUpload()
  selectedFile.value = file
  if (!projectName.value.trim()) projectName.value = file.name.replace(/\.[^.]+$/, '')
  uploadState.value = 'uploading'
  try {
    stagedUpload.value = await api.uploadRemakeVideo(file)
    uploadState.value = 'ready'
  } catch (error) {
    uploadState.value = 'failed'
    errorMessage.value = (error as Error).message || '视频上传失败'
  }
}

function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) void uploadFile(file)
  input.value = ''
}

async function removeFile() {
  await releaseCurrentUpload()
  selectedFile.value = null
  uploadState.value = 'empty'
  errorMessage.value = ''
}

async function loadHistoryProjects() {
  loadingHistory.value = true
  errorMessage.value = ''
  try {
    const response = await api.remakeHistoryProjects('', 1, 50)
    historyProjects.value = response.data.items
  } catch (error) {
    errorMessage.value = (error as Error).message || '历史项目加载失败'
  } finally {
    loadingHistory.value = false
  }
}

async function selectSourceMode(mode: SourceMode) {
  if (!capabilities.value?.source_modes[mode]) return
  const previous = sourceMode.value
  if (previous === 'folder_upload' && mode !== previous) {
    await releaseFolderUploads()
    folderEntries.value = []
    missingFolderEpisodes.value = []
  }
  sourceMode.value = mode
  errorMessage.value = ''
  if (mode !== 'single_upload') {
    await releaseCurrentUpload()
    selectedFile.value = null
    uploadState.value = 'empty'
    if (mode === 'history' && !historyProjects.value.length) await loadHistoryProjects()
  }
}

async function uploadFolderEntries(entries: FolderVideoEntry[]) {
  const queue = entries.filter(entry => entry.state === 'pending' || entry.state === 'failed')
  if (!queue.length) return
  uploadingFolder.value = true
  let cursor = 0
  const worker = async () => {
    while (cursor < queue.length) {
      const entry = queue[cursor++]
      if (!entry) continue
      entry.state = 'uploading'
      entry.progress = 1
      entry.issue = ''
      try {
        const upload = await api.uploadRemakeVideo(entry.file, progress => {
          entry.progress = Math.max(entry.progress, Math.min(99, progress))
        })
        entry.uploadToken = upload.upload_token
        entry.durationSeconds = upload.duration_seconds
        entry.progress = 100
        entry.state = 'ready'
      } catch (error) {
        entry.state = 'failed'
        entry.issue = (error as Error).message || '上传失败'
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(3, queue.length) }, () => worker()))
  uploadingFolder.value = false
}

async function handleFolderChange(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  await releaseFolderUploads()
  errorMessage.value = ''
  gapConfirmed.value = false
  const batch = prepareFolderBatch(
    files,
    capabilities.value?.media.extensions ?? ['mp4', 'mov'],
    capabilities.value?.media.max_bytes ?? 500 * 1024 * 1024,
  )
  folderEntries.value = batch.entries
  missingFolderEpisodes.value = batch.missingEpisodes
  const firstPath = batch.entries[0]?.relativePath ?? ''
  const folderName = firstPath.includes('/') ? firstPath.split('/')[0] : ''
  if (!projectName.value.trim() && folderName) projectName.value = `${folderName}重制版`
  if (!batch.hasBlockingIssues) await uploadFolderEntries(folderEntries.value)
}

async function retryFolderEntry(entry: FolderVideoEntry) {
  entry.state = 'pending'
  entry.progress = 0
  await uploadFolderEntries([entry])
}

async function selectHistoryProject(project: RemakeHistoryProject) {
  selectedHistoryProjectId.value = project.id
  selectedHistoryChapterId.value = null
  historyEpisodes.value = []
  loadingEpisodes.value = true
  errorMessage.value = ''
  if (!projectName.value.trim()) projectName.value = `${project.name}重制版`
  try {
    const response = await api.remakeHistoryEpisodes(project.id)
    historyEpisodes.value = response.data
  } catch (error) {
    errorMessage.value = (error as Error).message || '历史剧集加载失败'
  } finally {
    loadingEpisodes.value = false
  }
}

function selectHistoryEpisode(episode: RemakeHistoryEpisode) {
  if (episode.available) selectedHistoryChapterId.value = episode.chapter_id
}

async function createProject() {
  if (!canSubmit.value) return
  creating.value = true
  errorMessage.value = ''
  try {
    const sources = sourceMode.value === 'history'
      ? [{ source_chapter_id: selectedHistoryChapterId.value as number }]
      : sourceMode.value === 'folder_upload'
        ? folderEntries.value
            .filter((entry): entry is FolderVideoEntry & { episodeNumber: number; uploadToken: string } => entry.state === 'ready' && entry.episodeNumber !== null && Boolean(entry.uploadToken))
            .map(entry => ({ episode_number: entry.episodeNumber, upload_token: entry.uploadToken }))
        : [{ episode_number: 1, upload_token: (stagedUpload.value as RemakeUpload).upload_token }]
    const response = await api.createRemakeProject({
      name: projectName.value.trim(),
      source_mode: sourceMode.value,
      aspect_ratio: aspectRatio.value,
      resolution: resolution.value,
      style_key: ['auto', 'custom'].includes(styleKey.value) ? null : styleKey.value,
      custom_style_prompt: customStyleSelected.value ? customStylePrompt.value.trim() : null,
      idempotency_key: idempotencyKey.value,
      sources,
    })
    projectCommitted.value = true
    await router.push(response.data.entry_path)
  } catch (error) {
    errorMessage.value = (error as Error).message || '重制项目创建失败'
  } finally {
    creating.value = false
  }
}

onMounted(() => { void loadCapabilities() })
onBeforeUnmount(() => {
  void releaseCurrentUpload()
  void releaseFolderUploads()
})
</script>

<template>
  <CreationEntryShell
    eyebrow="AI REMAKE WORKSHOP"
    description="上传成片或选择历史项目，让 AI 自动拆出设定与分镜并开启新一轮创作。"
    width="wide"
  >
    <template #title>拆解成片，重制<span class="creation-entry-accent">精品短剧</span></template>
    <section v-if="loadingCapabilities" class="state-card" aria-live="polite">
      <RefreshCcw class="spin" :size="20" /> 正在加载重制能力…
    </section>
    <section v-else-if="capabilityError" class="state-card state-card--error" role="alert">
      <span>{{ capabilityError }}</span>
      <AppButton variant="secondary" size="sm" @click="loadCapabilities">重新加载</AppButton>
    </section>

    <form v-else-if="capabilities" class="remake-form" @submit.prevent="createProject">
      <Transition name="source-panel" mode="out-in">
        <label v-if="sourceMode === 'single_upload' && uploadState !== 'ready'" key="single-upload" class="source-stage upload-zone" :class="{ 'is-uploading': uploadState === 'uploading' }">
          <span class="source-stage-icon"><UploadCloud :size="27" /></span>
          <strong>{{ uploadState === 'uploading' ? '正在上传并校验视频…' : '选择 MP4 / MOV 视频' }}</strong>
          <span>单视频不超过 500 MB，时长不超过 20 分钟</span>
          <input type="file" accept="video/mp4,video/quicktime,.mp4,.mov" :disabled="uploadState === 'uploading'" @change="handleFileChange" />
        </label>
        <article v-else-if="sourceMode === 'single_upload' && stagedUpload" key="single-ready" class="source-stage uploaded-file">
          <span class="source-stage-icon is-ready"><CheckCircle2 :size="25" /></span>
          <div><strong>{{ stagedUpload.original_filename }}</strong><small>{{ fileMeta }}</small></div>
          <AppButton type="button" variant="ghost" size="sm" icon-only aria-label="移除视频" @click="removeFile"><X :size="17" /></AppButton>
        </article>

        <div v-else-if="sourceMode === 'folder_upload'" key="folder-upload" class="source-stage folder-selector">
          <label class="folder-zone" :class="{ 'is-uploading': uploadingFolder }">
            <span class="source-stage-icon"><FolderUp :size="25" /></span>
            <span><strong>{{ folderEntries.length ? '重新选择文件夹' : '选择包含多集视频的文件夹' }}</strong><small>文件名需包含“第12集 / EP12 / E12”等集数信息</small></span>
            <input data-folder-input type="file" accept="video/mp4,video/quicktime,.mp4,.mov" multiple webkitdirectory="" :disabled="uploadingFolder" @change="handleFolderChange" />
          </label>
          <div v-if="folderEntries.length" class="folder-table-wrap">
            <table class="folder-table">
              <thead><tr><th>集数</th><th>文件名</th><th>大小</th><th>状态 / 进度</th><th>问题</th><th>操作</th></tr></thead>
              <tbody>
                <tr v-for="entry in folderEntries" :key="entry.id" :data-folder-episode="entry.episodeNumber ?? undefined">
                  <td>{{ entry.episodeNumber ?? '—' }}</td>
                  <td :title="entry.relativePath">{{ entry.file.name }}</td>
                  <td>{{ formatFileSize(entry.file.size) }}</td>
                  <td><span class="folder-status" :class="`is-${entry.state}`">{{ folderStateLabel(entry) }}</span><progress v-if="entry.state === 'uploading'" :value="entry.progress" max="100" /></td>
                  <td class="folder-issue">{{ entry.issue || '—' }}</td>
                  <td><AppButton v-if="entry.state === 'failed'" type="button" variant="secondary" size="sm" @click="retryFolderEntry(entry)">重试</AppButton><span v-else>—</span></td>
                </tr>
              </tbody>
            </table>
          </div>
          <label v-if="missingFolderEpisodes.length" class="gap-warning">
            <input v-model="gapConfirmed" type="checkbox" />
            <span><strong>检测到断集：缺少第 {{ missingFolderEpisodes.join('、') }} 集</strong><small>断集不会阻止创建，但需要确认后继续。</small></span>
          </label>
        </div>

        <div v-else-if="sourceMode === 'history'" key="history" class="source-stage history-selector">
          <div class="history-column">
            <strong>历史项目</strong>
            <span v-if="loadingHistory" class="history-state"><RefreshCcw class="spin" :size="15" /> 正在加载…</span>
            <span v-else-if="!historyProjects.length" class="history-state">暂无包含可用剧集的项目</span>
            <button
              v-for="project in historyProjects"
              :key="project.id"
              type="button"
              class="history-option"
              :class="{ 'is-selected': selectedHistoryProjectId === project.id }"
              :data-history-project="project.id"
              @click="selectHistoryProject(project)"
            >
              <span><strong>{{ project.name }}</strong><small>{{ project.available_episode_count }} 集可重制</small></span>
              <ChevronRight :size="16" />
            </button>
          </div>
          <div class="history-column">
            <strong>选择剧集</strong>
            <span v-if="selectedHistoryProjectId === null" class="history-state">请先选择历史项目</span>
            <span v-else-if="loadingEpisodes" class="history-state"><RefreshCcw class="spin" :size="15" /> 正在检查完整性…</span>
            <button
              v-for="episode in historyEpisodes"
              v-else
              :key="episode.chapter_id"
              type="button"
              class="history-option history-episode"
              :class="{ 'is-selected': selectedHistoryChapterId === episode.chapter_id }"
              :data-history-episode="episode.chapter_id"
              :disabled="!episode.available"
              @click="selectHistoryEpisode(episode)"
            >
              <span><strong>{{ episode.name }}</strong><small v-if="episode.available">{{ episode.scene_count }} 个镜头 · {{ formatDuration(episode.duration_seconds) }}</small><small v-else>{{ episode.unavailable_reason }}</small></span>
              <CheckCircle2 v-if="selectedHistoryChapterId === episode.chapter_id" :size="17" />
            </button>
          </div>
        </div>
      </Transition>

      <CreationConfigBar modes-label="来源类型">
        <template #modes>
          <AppButton type="button" variant="soft" size="sm" :active="sourceMode === 'single_upload'" data-source-mode="single_upload" :aria-pressed="sourceMode === 'single_upload'" :disabled="!capabilities.source_modes.single_upload" @click="selectSourceMode('single_upload')">
            <Film :size="15" />单视频
          </AppButton>
          <AppButton type="button" variant="soft" size="sm" :active="sourceMode === 'folder_upload'" data-source-mode="folder_upload" :aria-pressed="sourceMode === 'folder_upload'" :disabled="!capabilities.source_modes.folder_upload" @click="selectSourceMode('folder_upload')">
            <FolderUp :size="15" />文件夹
          </AppButton>
          <AppButton type="button" variant="soft" size="sm" :active="sourceMode === 'history'" data-source-mode="history" :aria-pressed="sourceMode === 'history'" :disabled="!capabilities.source_modes.history" @click="selectSourceMode('history')">
            <History :size="15" />历史项目
          </AppButton>
        </template>

        <AppSelect v-model="aspectRatio" class="format-select" ariaLabel="画面比例" :options="capabilities.aspect_ratios">
          <template #leading><Film :size="15" /></template>
        </AppSelect>
        <AppSelect v-model="resolution" class="format-select" ariaLabel="清晰度" :options="capabilities.resolutions">
          <template #leading><Monitor :size="15" /></template>
        </AppSelect>
        <AppSelect v-model="styleKey" class="style-select" ariaLabel="视觉风格" menu-label="风格" :menu-width="230" :max-menu-height="404" align="end" :options="visualStyleOptions">
          <template #leading="{ option }">
            <img v-if="option.image" class="select-thumbnail" :src="option.image" alt="" />
            <span v-else class="custom-style-icon"><Sparkles :size="16" /></span>
          </template>
          <template #option-leading="{ option }">
            <img v-if="option.image" class="select-thumbnail" :src="option.image" alt="" />
            <span v-else class="custom-style-icon"><Sparkles :size="16" /></span>
          </template>
        </AppSelect>
      </CreationConfigBar>

      <label class="project-name-field">
        <span>项目名称</span>
        <input v-model="projectName" name="projectName" required maxlength="255" placeholder="例如：都市短剧重制版" />
      </label>

      <div v-if="customStyleSelected" class="custom-prompt-panel">
        <label for="remake-custom-style">自定义风格 Prompt</label>
        <textarea id="remake-custom-style" v-model="customStylePrompt" required maxlength="2000" rows="4" placeholder="描述材质、光影、色彩与镜头运动风格" />
        <small>{{ customStylePrompt.length }} / 2000</small>
      </div>

      <p v-if="errorMessage" class="form-error" role="alert">{{ errorMessage }}</p>

      <AppButton class="create-remake" variant="primary" size="lg" block type="submit" :disabled="!canSubmit" :loading="creating">
        <span><Sparkles v-if="!creating" :size="18" />{{ creating ? '正在创建重制项目…' : '开始重制' }}</span>
        <ArrowRight v-if="!creating" class="create-arrow" :size="18" />
      </AppButton>
    </form>
  </CreationEntryShell>
</template>

<style scoped>
.remake-form { display: grid; }
.state-card { display: flex; min-height: 220px; align-items: center; justify-content: center; gap: 10px; border: 1px dashed #d8dbea; border-radius: 16px; background: #fbfbfe; }
.state-card--error { flex-direction: column; color: #b54b58; }
.source-stage { min-height: 220px; padding: 26px; border: 1px dashed #d8dbea; border-radius: 16px; background: #fbfbfe; box-sizing: border-box; }
.upload-zone { display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 9px; color: #6263ee; cursor: pointer; transition: border-color .15s ease, background-color .15s ease, box-shadow .15s ease; }
.upload-zone:hover, .upload-zone.is-uploading { border-color: #8586f7; background: #f8f8ff; box-shadow: 0 12px 34px rgb(91 92 246 / 8%); }
.upload-zone strong { color: #4a4f60; font-size: 14px; font-weight: 600; }.upload-zone > span:not(.source-stage-icon) { color: #a0a5b4; font-size: 11px; }.upload-zone input, .folder-zone input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.source-stage-icon { display: grid; width: 50px; height: 50px; margin-bottom: 3px; place-items: center; border: 1px solid #e6e7f2; border-radius: 14px; color: #7779ef; background: #fff; box-shadow: 0 8px 24px rgb(50 54 73 / 7%); }
.source-stage-icon.is-ready { color: #4d9a78; background: #f1faf6; }
.uploaded-file { position: relative; display: grid; place-items: center; align-content: center; gap: 9px; border-style: solid; }.uploaded-file div { display: grid; justify-items: center; gap: 4px; }.uploaded-file strong { max-width: 70%; color: #4a4f60; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.uploaded-file small { color: #8e94a5; font-size: 11px; }.uploaded-file :deep(.app-button) { position: absolute; top: 14px; right: 14px; }
.history-selector { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.history-column { display: flex; min-height: 166px; padding: 13px; flex-direction: column; gap: 8px; border: 1px solid var(--app-border); border-radius: 14px; background: var(--app-surface-muted); }
.history-column > strong { padding: 2px 3px 5px; color: var(--app-text-secondary); font-size: 11px; }
.history-state { display: flex; flex: 1; align-items: center; justify-content: center; gap: 7px; color: var(--app-text-muted); font-size: 11px; text-align: center; }
.history-option { display: flex; width: 100%; padding: 11px 12px; align-items: center; justify-content: space-between; gap: 10px; border: 1px solid transparent; border-radius: 10px; color: var(--app-text); background: var(--app-surface); font: inherit; text-align: left; cursor: pointer; }
.history-option > span { display: grid; gap: 3px; }.history-option strong { font-size: 12px; }.history-option small { color: var(--app-text-muted); font-size: 10px; line-height: 1.45; }
.history-option.is-selected { border-color: rgb(98 99 238 / 35%); color: #5b5ced; background: rgb(98 99 238 / 7%); }
.history-option:disabled { opacity: .58; cursor: not-allowed; }.history-episode:disabled small { color: #b66a73; }
.folder-selector { display: grid; min-height: 220px; gap: 12px; }
.folder-zone { display: flex; min-height: 66px; padding: 0 4px; align-items: center; gap: 12px; color: #6263ee; cursor: pointer; }.folder-zone .source-stage-icon { width: 46px; height: 46px; margin: 0; flex: 0 0 auto; }
.folder-zone > span:not(.source-stage-icon) { display: grid; gap: 3px; }.folder-zone strong { color: var(--app-text); font-size: 12px; }.folder-zone small { color: var(--app-text-muted); font-size: 10px; }
.folder-table-wrap { overflow-x: auto; border: 1px solid var(--app-border); border-radius: 13px; }
.folder-table { width: 100%; border-collapse: collapse; font-size: 11px; }.folder-table th, .folder-table td { padding: 10px 11px; border-bottom: 1px solid var(--app-border); text-align: left; white-space: nowrap; }.folder-table th { color: var(--app-text-muted); background: var(--app-surface-muted); font-size: 10px; }.folder-table tbody tr:last-child td { border-bottom: 0; }.folder-table td:nth-child(2) { max-width: 240px; overflow: hidden; text-overflow: ellipsis; }.folder-table progress { display: block; width: 74px; height: 4px; margin-top: 4px; }
.folder-status { color: var(--app-text-secondary); }.folder-status.is-ready { color: #258c62; }.folder-status.is-failed, .folder-status.is-invalid { color: #bd4d5a; }.folder-status.is-ignored { color: var(--app-text-muted); }.folder-issue { max-width: 240px; color: #bd4d5a; overflow: hidden; text-overflow: ellipsis; }
.gap-warning { display: flex; padding: 12px 13px; align-items: flex-start; gap: 9px; border: 1px solid rgb(207 154 42 / 28%); border-radius: 12px; background: rgb(207 154 42 / 7%); cursor: pointer; }.gap-warning input { margin-top: 2px; }.gap-warning span { display: grid; gap: 3px; }.gap-warning strong { color: #9a6a12; font-size: 11px; }.gap-warning small { color: var(--app-text-muted); font-size: 10px; }
.form-error { margin: 11px 0 0; color: #bd4d5a; font-size: 12px; }
.format-select { width: 110px; }.style-select { width: 136px; }
.select-thumbnail { width: 24px; height: 24px; flex: 0 0 auto; border-radius: 6px; object-fit: cover; }.custom-style-icon { display: grid; width: 24px; height: 24px; flex: 0 0 auto; place-items: center; border-radius: 6px; color: #6466ef; background: #eff0ff; }
.project-name-field { display: flex; min-height: 44px; align-items: center; gap: 12px; margin-top: 10px; padding: 0 14px; border: 1px solid #e8e9ef; border-radius: 12px; background: #fff; box-shadow: 0 7px 20px rgb(35 39 52 / 4%); }.project-name-field span { flex: 0 0 auto; color: #727789; font-size: 11px; font-weight: 650; }.project-name-field input { min-width: 0; flex: 1; border: 0; outline: 0; color: #3e4352; background: transparent; font: inherit; font-size: 12px; }.project-name-field input::placeholder { color: #a2a7b5; }
.custom-prompt-panel { position: relative; display: grid; gap: 8px; margin-top: 12px; padding: 14px; border: 1px solid #e4e6ed; border-radius: 12px; background: #fbfbfd; }.custom-prompt-panel label { color: #505566; font-size: 12px; font-weight: 600; }.custom-prompt-panel textarea { width: 100%; border: 0; outline: 0; color: #3e4352; background: transparent; font: inherit; font-size: 13px; line-height: 1.7; resize: vertical; }.custom-prompt-panel small { justify-self: end; color: #a2a7b5; font-size: 10px; }
.create-remake { position: relative; display: inline-flex; width: 100%; min-height: 52px; align-items: center; justify-content: center; margin-top: 14px; padding: 0 52px; border: 1px solid #5354ed; border-radius: 13px; color: #fff; background: #5b5cf6; box-shadow: 0 14px 30px rgb(91 92 246 / 22%); font-size: 14px; font-weight: 700; transition: transform .15s ease, background-color .15s ease, box-shadow .15s ease; }.create-remake > span { display: inline-flex; align-items: center; gap: 9px; }.create-remake .create-arrow { position: absolute; right: 20px; }.create-remake:hover:not(:disabled) { background: #4c4de8; box-shadow: 0 16px 34px rgb(91 92 246 / 28%); transform: translateY(-1px); }
.source-panel-enter-active, .source-panel-leave-active { transition: opacity .16s ease, transform .16s ease; }.source-panel-enter-from, .source-panel-leave-to { opacity: 0; transform: translateY(5px); }
.spin { animation: spin .9s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 880px) { .format-select { width: 118px; }.style-select { width: 150px; } }
@media (max-width: 620px) { .source-stage { min-height: 190px; padding: 18px 14px; }.history-selector { grid-template-columns: 1fr; }.format-select { width: calc(50% - 4px); }.style-select { width: 100%; }.folder-table td:nth-child(2) { max-width: 150px; }.project-name-field { align-items: flex-start; flex-direction: column; gap: 4px; padding: 10px 12px; }.project-name-field input { width: 100%; } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
</style>
