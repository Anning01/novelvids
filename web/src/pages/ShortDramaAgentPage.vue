<script setup lang="ts">
import { tr, dateLocale } from '@/i18n'

import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowRight,
  Check,
  Clapperboard,
  GalleryHorizontalEnd,
  Timer,
  FileText,
  Film,
  MonitorPlay,
  Palette,
  Pencil,
  RefreshCw,
  Save,
  Sparkles,
  UsersRound,
  Volume2,
  X,
} from 'lucide-vue-next'
import { api } from '@/api'
import { agentApi } from '@/features/creation-agent/api'
import EpisodePacingDialog from '@/components/EpisodePacingDialog.vue'
import type { EpisodePacing } from '@/types'
import { useCreationAgentWorkspace } from '@/features/creation-agent/workspace'
import { useAuthStore } from '@/features/auth/authStore'
import ImageModelSelect from '@/components/ImageModelSelect.vue'
import AppBadge from '@/components/AppBadge.vue'
import AppSelect from '@/components/AppSelect.vue'
import AudioReferencePicker from '@/components/AudioReferencePicker.vue'
import ShortDramaWorkspaceShell from '@/components/ShortDramaWorkspaceShell.vue'
import { appConfirm } from '@/shared/confirmDialog'
import { notice } from '@/shared/notice'
import { episodeDisplayLabel } from '@/shared/chapterTitle'
import EpisodeScreenplay from '@/components/EpisodeScreenplay.vue'
import {pollUntilTerminal} from '@/features/workbench/execution/workbenchAsync'
import ProjectCover from '@/components/ProjectCover.vue'
import {
  chapterDraftChanged,
  createChapterEditDraft,
  createProjectAnalysisDraft,
  normalizeTags,
  projectPatchFromDraft,
  resolveStoryboardStrategy,
} from '@/shared/projectAnalysisEditor'
import { readShortDramaSettings } from '@/shared/shortDramaProject'
import { usePagedChapters } from '@/shared/pagedChapters'
import { AssetTypeEnum, TaskStatusEnum } from '@/types'
import type {
  ChapterEditDraft,
  ProjectAnalysisDraft,
} from '@/shared/projectAnalysisEditor'
import type { AiTask, Asset, AudioReference, Chapter, Novel, RemakeCapabilities, StoryboardStrategy } from '@/types'

interface AgentProjectMeta {
  projectId?: number
  name: string
  aspectRatio: string
  resolution: string
  style: string
  fileName: string
  sourcePath?: string
  cover?: string
  coverPreview?: string
  analysisTaskId?: string
}

interface KeyCharacter {
  name: string
  aliases: string[]
  role: string
  description: string
  base_traits: string
  chapter_numbers: number[]
}

interface ProjectAnalysisResult {
  book_types: string[]
  story_outline: string
  key_characters: KeyCharacter[]
  chapter_count: number
  cover: string | null
  analysis_completed?: boolean
  cover_status?: string
  cover_warning?: string
  cover_error?: string
}

const fallbackProject: AgentProjectMeta = {
  name: tr('短剧项目'),
  aspectRatio: '9:16',
  resolution: '720p',
  style: tr('写实通用'),
  fileName: '',
}

function readProjectMeta(): AgentProjectMeta {
  try {
    const stored = sessionStorage.getItem('short-drama-agent-project')
    return stored ? { ...fallbackProject, ...JSON.parse(stored) } : fallbackProject
  } catch {
    return fallbackProject
  }
}

const project = ref(readProjectMeta())
const novel = ref<Novel | null>(null)
const manuscriptLength = ref(0)
const hasAnalysisContent = computed(() => manuscriptLength.value > 0 || (novel.value?.total_chapters || 0) > 0)
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const projectId = computed(() => Number(route.params.projectId))
const activeEpisode = ref(1)
const episodeBusy = ref(false)
const analysisTask = ref<AiTask | null>(null)
const analysisError = ref('')
const {
  chapters,
  total: chaptersTotal,
  loading: chaptersLoading,
  hasMore: chaptersHasMore,
  loadMore: loadMoreChapters,
  reset: resetChapters,
  ensureChapter,
} = usePagedChapters(() => projectId.value)
const chapterDetails = ref<Record<number, Chapter>>({})
const chapterAssets = ref<Record<number, Asset[]>>({})
const loadingChapterId = ref<number | null>(null)
const startingAnalysis = ref(false)
const editing = ref(false)
const savingEdits = ref(false)
const pendingStoryboard = ref<boolean | null>(null)
const savingStoryboard = computed(() => pendingStoryboard.value !== null)
const savingDuration = ref(false)
const durationPreview = ref<number | null>(null)
const projectDraft = ref<ProjectAnalysisDraft | null>(null)
const initialProjectDraft = ref<ProjectAnalysisDraft | null>(null)
const storyboardStrategies = ref<StoryboardStrategy[]>([])
const narratorVoice = ref<AudioReference | null>(null)
const narratorVoiceBeforeEditing = ref<AudioReference | null>(null)
const narratorPickerOpen = ref(false)
const chapterDrafts = ref<Record<number, ChapterEditDraft>>({})
const episodeTabs = ref<HTMLElement | null>(null)
let pollTimer: number | undefined

const analysisResult = computed<ProjectAnalysisResult | null>(() => {
  const task = analysisTask.value
  if (!task?.response_data || (task.status !== TaskStatusEnum.COMPLETED && task.response_data.analysis_completed !== true)) return null
  return task.response_data as unknown as ProjectAnalysisResult
})
const projectView = computed(() => createProjectAnalysisDraft(
  novel.value ?? { name: project.value.name },
  analysisResult.value,
  storyboardStrategies.value,
))
const projectStrategyView = computed(() => resolveStoryboardStrategy(
  projectView.value.storyboardStrategy,
  storyboardStrategies.value,
))
const narrationStrategyActive = computed(() => (
  editing.value && projectDraft.value
    ? projectDraft.value.storyboardStrategy
    : projectStrategyView.value?.key
) === 'narration')
const storyboardStrategyOptions = computed(() => storyboardStrategies.value.map(strategy => ({
  value: strategy.key,
  get label() { return tr(strategy.name) },
})))
const displayedProjectName = computed(() => editing.value && projectDraft.value
  ? projectDraft.value.name
  : project.value.name)
const displayedTags = computed(() => normalizeTags(projectView.value.tagsText))
const selectedEpisodeBrief = computed(() => chapters.value.find(item => item.number === activeEpisode.value) ?? chapters.value[0])
const selectedEpisode = computed(() => {
  const chapter = selectedEpisodeBrief.value
  return chapter ? (chapterDetails.value[chapter.id] ?? chapter) : undefined
})
type EpisodeView = 'source' | 'screenplay'
const episodeViews = ref<Record<number, EpisodeView>>({})
const episodeView = computed(() => selectedEpisode.value &&
  (episodeViews.value[selectedEpisode.value.id] ?? (selectedEpisode.value.screenplay || !selectedEpisode.value.content?.trim() ? 'screenplay' : 'source')))
const generatingScripts = ref<Record<number, boolean>>({})
const scriptRequests = new AbortController()
const adapting = computed(() => Object.keys(generatingScripts.value).length > 0)

function taskKey(id: number) { return `novelvids:screenplay:${projectId.value}:${id}` }

async function saveEpisodePacing(id: number, pacing: EpisodePacing) {
  const { data } = await api.updateChapter(id, { episode_pacing: pacing })
  chapterDetails.value[id] = data
  notice.success(tr('本集设置已保存'))
}

async function generateScreenplay(id: number, existingTask = sessionStorage.getItem(taskKey(id))) {
  if (generatingScripts.value[id] || (!existingTask && (!canEdit.value || editing.value || !analysisModelId.value))) return
  const previous = chapterDetails.value[id]?.screenplay
  if (!existingTask && previous && !await appConfirm({
    title: tr('重新生成本集剧本'),
    message: tr('将根据本集原文重新改编，成功后替换当前导演剧本。'),
    confirmLabel: tr('重新生成'),
  })) return
  generatingScripts.value[id] = true
  try {
    const taskId = existingTask || (await api.generateScreenplay(id, previous || undefined, Number(analysisModelId.value))).data.id
    sessionStorage.setItem(taskKey(id), taskId)
    const task = await pollUntilTerminal(async signal => (await api.task(taskId, signal)).data, {
      signal: scriptRequests.signal, intervalMs: 1200,
      terminalStatuses: new Set([TaskStatusEnum.COMPLETED, TaskStatusEnum.FAILED, TaskStatusEnum.CANCELLED]),
    })
    sessionStorage.removeItem(taskKey(id))
    if (task.status !== TaskStatusEnum.COMPLETED) throw new Error(task.error_message || tr('剧本生成未完成'))
    const chapter = (await api.chapter(id)).data
    if (!chapter.screenplay) throw new Error(tr('未读取到本集导演剧本'))
    chapterDetails.value[id] = chapter
    episodeViews.value[id] = 'screenplay'
  } catch (error) {
    if (!scriptRequests.signal.aborted) notice.error((error as Error).message)
  } finally {
    delete generatingScripts.value[id]
  }
}

const selectedEpisodeDraft = computed(() => {
  const chapter = selectedEpisode.value
  return chapter ? chapterDrafts.value[chapter.id] : undefined
})
const selectedEpisodeLoading = computed(() => {
  const chapter = selectedEpisodeBrief.value
  return Boolean(chapter && loadingChapterId.value === chapter.id && !chapterDetails.value[chapter.id])
})
const selectedEpisodeCharacters = computed(() => {
  const chapter = selectedEpisodeBrief.value
  if (!chapter) return tr('暂无当前章节角色')
  return (chapterAssets.value[chapter.id] || [])
    .filter(asset => asset.asset_type === AssetTypeEnum.PERSON)
    .map(asset => asset.canonical_name)
    .join('、') || tr('暂无当前章节角色')
})
const canEdit = computed(() => (
  auth.enabled !== true
  || auth.role === 'admin'
  || auth.role === 'creator'
  || auth.role === 'super'
))
const hasScriptPreview = computed(() => Boolean(
  analysisResult.value
  || chaptersTotal.value
  || novel.value?.total_chapters
  || novel.value?.episodes_managed
))
const analysisRunning = computed(() => {
  const status = analysisTask.value?.status
  return status === TaskStatusEnum.PENDING || status === TaskStatusEnum.PROCESSING || status === TaskStatusEnum.QUEUED
})
const analysisStatus = computed(() => {
  if (analysisRunning.value && analysisTask.value?.response_data?.cover_status === 'pending') return tr('分析已完成，封面生成中')
  if (startingAnalysis.value || analysisRunning.value) return tr('正在理解故事')
  if (analysisResult.value) return tr('剧本分析完成')
  if (analysisTask.value?.status === TaskStatusEnum.FAILED) return tr('分析失败')
  if (hasScriptPreview.value) return tr('剧本已载入')
  return hasAnalysisContent.value ? tr('准备分析') : tr('待添加分集')
})
async function loadProject(): Promise<boolean> {
  if (!Number.isFinite(projectId.value) || projectId.value <= 0) return false
  try {
    const response = await api.novelMeta(projectId.value)
    novel.value = response.data as unknown as Novel
    if (response.data.narrator_audio_reference_id) {
      const voices = await api.audioReferences(1, '', { id: response.data.narrator_audio_reference_id })
      narratorVoice.value = voices.data.items[0] || null
    } else {
      narratorVoice.value = null
    }
    const contentLength = response.data.content_length || 0
    manuscriptLength.value = contentLength
    if (!response.data.episodes_managed && contentLength >= 30_000 && (response.data.total_chapters || 0) <= 1) {
      notice.error(tr('书稿约 {p0} 字但只拆分出 {p1} 章，已阻止进入。请重新上传并检查文件编码或章节标题。', { p0: contentLength.toLocaleString(dateLocale.value), p1: response.data.total_chapters || 0 }))
      await router.replace('/create/short-drama')
      return false
    }
    const settings = readShortDramaSettings(response.data)
    project.value = {
      ...project.value,
      projectId: response.data.id,
      name: response.data.name,
      aspectRatio: settings.aspectRatio || project.value.aspectRatio,
      resolution: settings.resolution || project.value.resolution,
      style: settings.style || project.value.style,
      fileName: settings.sourceFile || project.value.fileName,
      cover: response.data.cover,
      coverPreview: response.data.cover_preview || undefined,
    }
    return true
  } catch (error) {
    notice.error((error as Error).message)
    return false
  }
}

const displayOptions = ref<Pick<RemakeCapabilities, 'aspect_ratios' | 'resolutions' | 'styles'> | null>(null)
async function loadDisplayOptions() {
  try {
    displayOptions.value = (await api.remakeCapabilities()).data
  } catch (error) {
    notice.error((error as Error).message)
  }
}

const resolutionOptions = computed(() => {
  const values = new Map<string, string>()
  for (const value of displayOptions.value?.resolutions || []) {
    if (!values.has(value.toLowerCase()) || value === project.value.resolution) values.set(value.toLowerCase(), value)
  }
  return [...values.values()]
})
const styleOptions = computed(() => [
  ...(displayOptions.value?.styles || []).filter(item => item.key !== 'custom').map(item => ({value: item.key, label: tr(item.label)})),
  {value: 'custom', label: tr('自定义风格'), separator: true},
])
const displayStyle = computed(() => {
  const key = projectView.value.styleKey
  return styleOptions.value.find(item => item.value === key)?.label || (key === 'auto' ? tr('AI 识别风格') : key || project.value.style)
})

async function loadStoryboardStrategies() {
  try {
    const response = await api.storyboardStrategies()
    storyboardStrategies.value = response.data
  } catch (error) {
    notice.error((error as Error).message)
  }
}

async function loadChapters(preferredId = Number(route.query.chapter)) {
  try {
    resetChapters()
    await loadMoreChapters()
    const requestedChapterId = preferredId
    const requestedChapter = await ensureChapter(requestedChapterId)
    if (requestedChapter) {
      activeEpisode.value = requestedChapter.number
    } else if (chapters.value.length && !chapters.value.some(item => item.number === activeEpisode.value)) {
      activeEpisode.value = chapters.value[0].number
    }
    await loadChapterContent(selectedEpisodeBrief.value)
  } catch (error) {
    notice.error((error as Error).message)
  }
}

async function loadChapterContent(chapter?: Chapter) {
  if (!chapter) return
  const needsContent = !chapterDetails.value[chapter.id]
  if (needsContent) loadingChapterId.value = chapter.id
  try {
    const [detailResponse, assetResponse] = await Promise.all([
      needsContent ? api.chapter(chapter.id) : Promise.resolve(null),
      api.assets(projectId.value, 1, 100, chapter.id),
    ])
    chapterAssets.value = {
      ...chapterAssets.value,
      [chapter.id]: assetResponse.data.items,
    }
    if (detailResponse) {
      const detail = detailResponse.data
      chapterDetails.value = { ...chapterDetails.value, [chapter.id]: detail }
      if (editing.value) ensureChapterDraft(detail)
      const existing = sessionStorage.getItem(taskKey(detail.id))
      if (existing) void generateScreenplay(detail.id, existing)
    }
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    if (needsContent && loadingChapterId.value === chapter.id) loadingChapterId.value = null
  }
}

function stopPolling() {
  if (pollTimer !== undefined) window.clearTimeout(pollTimer)
  pollTimer = undefined
}

async function pollAnalysis(taskId: string) {
  stopPolling()
  try {
    const response = await api.task(taskId)
    const hadResult = Boolean(analysisResult.value)
    analysisTask.value = response.data
    if (analysisRunning.value) {
      if (analysisResult.value && !hadResult) await loadProject()
      pollTimer = window.setTimeout(() => pollAnalysis(taskId), 1800)
    } else if (response.data.status === TaskStatusEnum.COMPLETED) {
      await Promise.all([loadProject(), loadChapters()])
    }
  } catch (error) {
    analysisError.value = tr('进度连接中断，可以重新连接。后台任务会继续处理。')
    notice.error((error as Error).message)
  }
}

const analysisModelId = ref('')
const analysisModels = ref<{ value: string; label: string }[]>([])
const loadingAnalysisModels = ref(true)
const analysisModelsError = ref('')
async function loadAnalysisModels() {
  loadingAnalysisModels.value = true
  analysisModelsError.value = ''
  try {
    const { data } = await agentApi.capabilities(projectId.value)
    analysisModels.value = data.models.map(model => ({ value: String(model.id), label: model.name || model.model }))
  } catch (error) {
    analysisModelsError.value = (error as Error).message
  } finally {
    loadingAnalysisModels.value = false
  }
}
const coverModelId = ref('')
const generatingCover = ref(false)
const coverError = ref('')
const hasCover = computed(() => Boolean(project.value.coverPreview || project.value.cover || analysisResult.value?.cover))

async function generateCover() {
  if (!canEdit.value || !coverModelId.value || generatingCover.value || startingAnalysis.value || analysisRunning.value) return
  generatingCover.value = true
  coverError.value = ''
  try {
    const { data } = await api.generateNovelCover(projectId.value, Number(coverModelId.value))
    const task = await pollUntilTerminal(async signal => (await api.task(data.id, signal)).data, {
      signal: scriptRequests.signal, intervalMs: 1200,
      terminalStatuses: new Set([TaskStatusEnum.COMPLETED, TaskStatusEnum.FAILED, TaskStatusEnum.CANCELLED]),
    })
    if (task.status !== TaskStatusEnum.COMPLETED || task.response_data?.cover_status !== 'ready') {
      throw new Error(task.error_message || String(task.response_data?.cover_error || tr('封面生成未完成')))
    }
    await loadProject()
  } catch (error) {
    if (!scriptRequests.signal.aborted) coverError.value = (error as Error).message
  } finally {
    generatingCover.value = false
  }
}

async function startAnalysis() {
  if (!canEdit.value || !analysisModelId.value || startingAnalysis.value || analysisRunning.value || generatingCover.value) return
  startingAnalysis.value = true
  analysisError.value = ''
  try {
    const response = await api.analyzeNovel(projectId.value, undefined, Number(analysisModelId.value))
    analysisTask.value = response.data
    notice.success(tr('AI 已开始提取类型、大纲和关键人物'))
    await pollAnalysis(response.data.id)
  } catch (error) {
    analysisError.value = error instanceof Error ? error.message : tr('分析未能开始，请重试')
    notice.error((error as Error).message)
  } finally {
    startingAnalysis.value = false
  }
}

async function loadAnalysis() {
  try {
    analysisError.value = ''
    await loadChapters()
    const response = await api.novelAnalysis(projectId.value)
    analysisTask.value = response.data
    if (response.data && analysisRunning.value) {
      await pollAnalysis(response.data.id)
    }
  } catch (error) {
    analysisError.value = error instanceof Error ? error.message : tr('无法读取分析进度')
    notice.error((error as Error).message)
  }
}

function ensureChapterDraft(chapter: Chapter) {
  if (chapterDrafts.value[chapter.id]) return
  chapterDrafts.value = {
    ...chapterDrafts.value,
    [chapter.id]: createChapterEditDraft(chapter),
  }
}

function beginEditing() {
  if (!novel.value || !canEdit.value || adapting.value) return
  narratorVoiceBeforeEditing.value = narratorVoice.value
  projectDraft.value = createProjectAnalysisDraft(
    novel.value,
    analysisResult.value,
    storyboardStrategies.value,
  )
  projectDraft.value.aspectRatio ||= project.value.aspectRatio
  projectDraft.value.resolution ||= project.value.resolution
  if (!displayOptions.value) void loadDisplayOptions()
  initialProjectDraft.value = { ...projectDraft.value }
  chapterDrafts.value = {}
  if (selectedEpisode.value) ensureChapterDraft(selectedEpisode.value)
  editing.value = true
}

function selectStoryboardStrategy(value: string) {
  if (!projectDraft.value) return
  projectDraft.value.storyboardStrategy = value
  const selected = resolveStoryboardStrategy(
    projectDraft.value.storyboardStrategy,
    storyboardStrategies.value,
  )
  if (!selected) return
  projectDraft.value.storyboardStrategy = selected.key
  projectDraft.value.storyboardSetting = selected.description
}

function selectNarratorVoice(reference: AudioReference) {
  narratorVoice.value = reference
  if (projectDraft.value) projectDraft.value.narratorAudioReferenceId = reference.id
  narratorPickerOpen.value = false
}

function cancelEditing(restoreVoice = true) {
  if (restoreVoice) narratorVoice.value = narratorVoiceBeforeEditing.value
  editing.value = false
  projectDraft.value = null
  initialProjectDraft.value = null
  chapterDrafts.value = {}
}

const storyboardEnabled = computed(() => editing.value && projectDraft.value
  ? projectDraft.value.storyboardEnabled
  : pendingStoryboard.value ?? projectView.value.storyboardEnabled)

async function toggleStoryboard() {
  if (!novel.value || !canEdit.value || savingEdits.value || savingStoryboard.value) return
  if (editing.value && projectDraft.value) {
    projectDraft.value.storyboardEnabled = !projectDraft.value.storyboardEnabled
    return
  }
  const enabled = !storyboardEnabled.value
  pendingStoryboard.value = enabled
  try {
    await api.updateNovel(projectId.value, { storyboard_enabled: enabled })
    novel.value = { ...novel.value, storyboard_enabled: enabled }
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    pendingStoryboard.value = null
  }
}

const durationSeconds = computed(() => durationPreview.value ?? (editing.value
  ? projectDraft.value?.shotDurationMax
  : projectView.value.shotDurationMax) ?? 15)

function previewDuration(event: Event) {
  const value = (event.currentTarget as HTMLInputElement).valueAsNumber
  if (editing.value && projectDraft.value) projectDraft.value.shotDurationMax = value
  else durationPreview.value = value
}

async function commitDuration(event: Event) {
  if (!novel.value || !canEdit.value || savingDuration.value || savingEdits.value) return
  previewDuration(event)
  if (editing.value) return
  const value = durationSeconds.value
  try {
    if (value === projectView.value.shotDurationMax) return
    savingDuration.value = true
    await api.updateNovel(projectId.value, {shot_duration_max: value})
    novel.value = {...novel.value, shot_duration_max: value}
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    durationPreview.value = null
    savingDuration.value = false
  }
}

async function saveEdits() {
  if (!novel.value || !projectDraft.value || savingEdits.value) return
  if (projectDraft.value.styleKey === 'custom' && !projectDraft.value.customStyle?.trim()) {
    notice.error(tr('自定义风格不能为空'))
    return
  }
  if (!Number.isInteger(projectDraft.value.shotDurationMax) || projectDraft.value.shotDurationMax! < 1 || projectDraft.value.shotDurationMax! > 30) {
    notice.error(tr('单分镜最长时长须为 1–30 秒'))
    return
  }
  const projectPatch = projectPatchFromDraft(projectDraft.value, initialProjectDraft.value)
  if ('name' in projectPatch && !projectPatch.name) {
    notice.error(tr('小说昵称不能为空'))
    return
  }

  const changedChapterDrafts = Object.values(chapterDrafts.value).filter((draft) => {
    const chapter = chapterDetails.value[draft.id]
    return chapter ? chapterDraftChanged(draft, chapter) : false
  })
  if (changedChapterDrafts.some(draft => !draft.name.trim())) {
    notice.error(tr('章节标题不能为空'))
    return
  }

  const hasProjectChanges = Object.keys(projectPatch).length > 0
  const hasChapterChanges = changedChapterDrafts.length > 0

  if (!hasProjectChanges && !hasChapterChanges) {
    cancelEditing(false)
    notice.info(tr('未检测到任何修改'))
    return
  }

  savingEdits.value = true
  try {
    const [projectResponse, chapterResponses] = await Promise.all([
      hasProjectChanges ? api.updateNovel(projectId.value, projectPatch) : Promise.resolve(null),
      hasChapterChanges
        ? Promise.all(changedChapterDrafts.map(draft => api.updateChapter(draft.id, {
            ...(draft.name.trim() !== createChapterEditDraft(chapterDetails.value[draft.id]!).name ? { name: draft.name.trim() } : {}),
            ...(draft.content !== (chapterDetails.value[draft.id]?.content ?? '') ? { content: draft.content } : {}),
            ...(draft.screenplay !== (chapterDetails.value[draft.id]?.screenplay ?? '') ? { screenplay: draft.screenplay } : {}),
          })))
        : Promise.resolve([]),
    ])
    if (projectResponse?.data) {
      novel.value = {
        ...novel.value,
        ...projectResponse.data,
      }
      project.value = {
        ...project.value,
        name: novel.value.name,
        aspectRatio: novel.value.aspect_ratio || project.value.aspectRatio,
        resolution: novel.value.resolution || project.value.resolution,
        cover: projectResponse.data.cover ?? project.value.cover,
        coverPreview: projectResponse.data.cover_preview || project.value.coverPreview,
      }
    }
    for (const response of chapterResponses) {
      const updated = response.data
      chapterDetails.value = { ...chapterDetails.value, [updated.id]: updated }
      chapters.value = chapters.value.map(chapter => chapter.id === updated.id
        ? { ...chapter, name: updated.name }
        : chapter)
    }
    cancelEditing(false)
    notice.success(tr('修改已保存{p0}', { p0: changedChapterDrafts.length ? `，同步更新 ${changedChapterDrafts.length} 个章节` : '' }))
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    savingEdits.value = false
  }
}

async function refreshAgentEpisodes() {
  if (editing.value) {
    notice.info(tr('助手修改已保存，当前编辑草稿已保留'))
    return
  }
  chapterDetails.value = {}
  await loadChapters(selectedEpisodeBrief.value?.id)
  if (selectedEpisodeBrief.value) await loadChapterContent(selectedEpisodeBrief.value)
}

async function addEpisode() {
  if (episodeBusy.value || editing.value || !canEdit.value) return
  episodeBusy.value = true
  try {
    const {data} = await api.createChapter({novel_id: projectId.value, content: ''})
    await loadChapters(data.id)
    await selectEpisode(data.number)
    beginEditing()
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    episodeBusy.value = false
  }
}

async function removeEpisode() {
  const target = selectedEpisodeBrief.value
  if (!target || episodeBusy.value || editing.value || !canEdit.value) return
  episodeBusy.value = true
  try {
    if (!await appConfirm({title: tr('删除本集'), message: episodeDisplayLabel(target), confirmLabel: tr('删除')})) return
    await api.deleteChapter(target.id)
    delete chapterDetails.value[target.id]
    delete chapterAssets.value[target.id]
    const neighbor = chapters.value.find(item => item.id !== target.id)
    await router.replace({query: {...route.query, chapter: neighbor ? String(neighbor.id) : undefined}})
    await loadChapters(neighbor?.id ?? 0)
    if (neighbor) await selectEpisode(neighbor.number)
    if (novel.value) novel.value.total_chapters = chaptersTotal.value
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    episodeBusy.value = false
  }
}

function continueToSettings() {
  notice.success(tr('剧本分析已确认，正在进入角色与场景设定'))
  void router.push({
    path: `/create/short-drama/manual/${projectId.value}`,
    query: selectedEpisodeBrief.value ? { chapter: String(selectedEpisodeBrief.value.id) } : undefined,
  })
}

async function selectEpisode(chapterNumber: number, event?: MouseEvent) {
  activeEpisode.value = chapterNumber
  const chapter = chapters.value.find(item => item.number === chapterNumber)
  if (chapter) void router.replace({ query: { ...route.query, chapter: String(chapter.id) } })
  await loadChapterContent(chapter)
  if (editing.value && selectedEpisode.value) ensureChapterDraft(selectedEpisode.value)
  await nextTick()
  const button = event?.currentTarget as HTMLElement | null
  if (!button || !episodeTabs.value) return
  const left = button.offsetLeft - (episodeTabs.value.clientWidth - button.offsetWidth) / 2
  episodeTabs.value.scrollTo({ left: Math.max(0, left), behavior: 'smooth' })
}

const episodeSentinel = ref<HTMLElement | null>(null)
let episodeObserver: IntersectionObserver | null = null
function observeEpisodeSentinel() {
  episodeObserver?.disconnect()
  if (episodeSentinel.value) {
    episodeObserver = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) void loadMoreChapters()
    }, { rootMargin: '300px' })
    episodeObserver.observe(episodeSentinel.value)
  }
}
onMounted(async () => {
  observeEpisodeSentinel()
  void loadDisplayOptions()
  if (canEdit.value) void loadAnalysisModels()
  const [, projectReady] = await Promise.all([
    loadStoryboardStrategies(),
    loadProject(),
  ])
  if (projectReady) await loadAnalysis()
  observeEpisodeSentinel()
})
onBeforeUnmount(() => {
  scriptRequests.abort()
  stopPolling()
  episodeObserver?.disconnect()
})
</script>

<template>
  <main class="agent-page">
    <ShortDramaWorkspaceShell
      @prompts-changed="refreshAgentEpisodes"
      :project-id="projectId"
      :project-name="displayedProjectName"
      :aspect-ratio="project.aspectRatio"
      :resolution="project.resolution"
      :style-name="displayStyle"
      active-phase="script"
      :show-episode-rail="false"
      :chapters="chapters"
      :active-chapter-id="selectedEpisodeBrief?.id || 0"
    >
      <section class="agent-content">
      <div class="analysis-hero">
        <ProjectCover :source="project.coverPreview || project.cover || analysisResult?.cover" :original="project.cover || analysisResult?.cover" :aspect-ratio="novel?.aspect_ratio || project.aspectRatio" :alt="tr('{p0}封面', { p0: displayedProjectName })" :max-width="144" :max-height="96" />
        <div class="analysis-hero-copy">
          <AppBadge
            class="analysis-ready"
            :tone="analysisRunning || startingAnalysis ? 'accent' : analysisResult ? 'success' : analysisTask?.status === TaskStatusEnum.FAILED ? 'danger' : 'neutral'"
          >
            <RefreshCw v-if="analysisRunning || startingAnalysis" class="status-spinner" :size="13" />
            <Check v-else-if="analysisResult" :size="13" />
            <FileText v-else :size="13" />
            {{ analysisStatus }}
          </AppBadge>
          <input v-if="editing && projectDraft" v-model="projectDraft.name" class="analysis-title-input" :aria-label="tr('小说昵称')" maxlength="255" />
          <h1 v-else>{{ project.name }}</h1>
          <div class="episode-project-meta">
            <span><FileText :size="14" />{{ chaptersTotal }} {{ tr('章') }}</span>
            <template v-if="editing && projectDraft">
              <label><Film :size="14" /><AppSelect density="compact" :ariaLabel="tr('画面比例')" :model-value="projectDraft.aspectRatio || project.aspectRatio" :options="displayOptions?.aspect_ratios || [project.aspectRatio]" :disabled="!displayOptions || savingEdits" @update:model-value="projectDraft.aspectRatio = $event" /></label>
              <label><MonitorPlay :size="14" /><AppSelect density="compact" :ariaLabel="tr('分辨率')" :model-value="projectDraft.resolution || project.resolution" :options="resolutionOptions.length ? resolutionOptions : [project.resolution]" :disabled="!displayOptions || savingEdits" @update:model-value="projectDraft.resolution = $event" /></label>
              <label><Palette :size="14" /><AppSelect density="compact" :ariaLabel="tr('视觉风格')" :model-value="projectDraft.styleKey || 'auto'" :options="styleOptions" :disabled="!displayOptions || savingEdits" @update:model-value="projectDraft.styleKey = $event" /></label>
            </template>
            <template v-else>
              <span><Film :size="14" />{{ project.aspectRatio }}</span>
              <span><MonitorPlay :size="14" />{{ project.resolution }}</span>
              <span :title="projectView.customStyle || displayStyle"><Palette :size="14" />{{ displayStyle }}</span>
            </template>
          </div>
          <label v-if="editing && projectDraft?.styleKey === 'custom'" class="tag-editor">
            <span>{{ tr('自定义风格') }}</span>
            <textarea v-model="projectDraft.customStyle" :aria-label="tr('自定义风格')" rows="2" maxlength="2000" />
          </label>
          <label v-if="editing && projectDraft" class="tag-editor">
            <span>{{ tr('项目标签') }}</span>
            <input v-model="projectDraft.tagsText" :placeholder="tr('使用逗号分隔，例如：都市，热血，成长')" />
          </label>
          <div v-else-if="displayedTags.length" class="genre-tags">
            <AppBadge v-for="(genre, index) in displayedTags" :key="genre" :tone="index % 2 ? 'success' : 'accent'" size="sm">{{ genre }}</AppBadge>
          </div>
        </div>
        <div class="analysis-hero-actions">
          <template v-if="editing">
            <AppButton variant="ghost" size="sm" type="button" :disabled="savingEdits" @click="cancelEditing"><X :size="15" />{{ tr('取消') }}</AppButton>
            <AppButton variant="primary" size="sm" type="button" :loading="savingEdits" @click="saveEdits"><Save :size="15" />{{ tr('保存修改') }}</AppButton>
          </template>
          <template v-else>
            <div v-if="canEdit && novel" class="cover-generation-actions">
              <ImageModelSelect v-model="coverModelId" :label="tr('封面生图模型')" :empty-label="tr('选择封面模型')"
                :disabled="generatingCover || analysisRunning || startingAnalysis" />
              <AppButton variant="secondary" size="sm" type="button" :loading="generatingCover"
                :disabled="!coverModelId || analysisRunning || startingAnalysis" @click="generateCover">
                {{ hasCover ? tr('重新生成封面') : tr('生成封面') }}
              </AppButton>
              <small v-if="coverError" class="cover-generation-error" role="alert">{{ coverError }}</small>
            </div>
            <div v-if="canEdit && hasAnalysisContent" class="cover-generation-actions">
              <AppButton class="secondary-action" variant="secondary" size="sm" type="button" :disabled="!analysisModelId || analysisRunning || startingAnalysis || generatingCover" @click="startAnalysis"><RefreshCw :size="15" />{{ tr('重新分析') }}</AppButton>
            </div>
            <AppButton v-if="canEdit && novel" variant="primary" size="sm" type="button" :disabled="savingStoryboard || savingDuration || adapting" @click="beginEditing"><Pencil :size="15" />{{ tr('编辑内容') }}</AppButton>
          </template>
        </div>
      </div>

      <section v-if="(!hasScriptPreview && hasAnalysisContent) || analysisRunning || startingAnalysis || analysisError || (analysisTask?.status === TaskStatusEnum.FAILED && !analysisResult)" class="analysis-progress-card" :class="{ 'is-failed': (analysisTask?.status === TaskStatusEnum.FAILED && !analysisResult) || analysisError }" role="status">
        <span><RefreshCw v-if="analysisRunning || startingAnalysis" class="status-spinner" :size="25" /><FileText v-else :size="25" /></span>
        <div>
          <h2>{{ analysisStatus }}</h2>
          <p v-if="analysisError">{{ analysisError }}</p>
          <p v-else-if="analysisRunning || startingAnalysis">{{ tr('正在理解故事、识别关键人物。正文已保存，分析完成后会自动更新。') }}</p>
          <p v-else-if="analysisTask?.status === TaskStatusEnum.FAILED">{{ analysisTask.error_message || tr('模型调用失败，请检查模型配置后重试。') }}</p>
          <p v-else>{{ tr('开始分析后，结果会自动保存在当前项目中。') }}</p>
        </div>
        <template v-if="canEdit && !selectedEpisode">
              <AppSelect v-model="analysisModelId" density="compact" :ariaLabel="tr('剧情分析模型')"
                :options="[{ value: '', label: loadingAnalysisModels ? tr('正在读取模型…') : analysisModels.length ? tr('选择分析模型') : tr('无可用模型') }, ...analysisModels]"
                :disabled="!analysisModels.length || analysisRunning || startingAnalysis || adapting || editing" />
              <small v-if="analysisModelsError" class="cover-generation-error" role="alert">{{ analysisModelsError }}</small>
              <AppButton v-if="analysisModelsError" variant="ghost" size="xs" @click="loadAnalysisModels">{{ tr('重试') }}</AppButton>
        </template>
        <AppButton v-if="canEdit && !analysisRunning && !startingAnalysis" variant="primary" size="sm" type="button" :disabled="!analysisModelId || generatingCover" @click="startAnalysis">{{ tr('开始分析') }}</AppButton>
        <AppButton v-if="analysisError" variant="secondary" size="sm" @click="loadAnalysis">{{ tr('重新连接') }}</AppButton>
      </section>

      <div v-if="analysisResult?.cover_warning" class="creation-cover-notice" role="status"><p>{{ analysisResult.cover_warning }}</p><p v-if="analysisResult.cover_error">{{ analysisResult.cover_error }}</p></div>
      <template v-if="novel">
      <div class="production-settings">
      <section class="analysis-section">
        <header><h2>{{ tr('项目设定') }}</h2></header>
        <div class="profile-grid">
          <article class="profile-card">
            <span><Clapperboard :size="18" /></span>
            <div>
              <small>{{ tr('分镜策略') }}</small>
              <template v-if="editing && projectDraft">
                <AppSelect
                  class="storyboard-strategy-select"
                  :model-value="projectDraft.storyboardStrategy"
                  :ariaLabel="tr('分镜策略')"
                  :menu-label="tr('分镜策略')"
                  :menu-width="230"
                  :options="storyboardStrategyOptions"
                  @update:model-value="selectStoryboardStrategy"
                />
                <p>{{ projectDraft.storyboardSetting }}</p>
                <button v-if="narrationStrategyActive" type="button" class="narrator-voice-button" @click="narratorPickerOpen = true">
                  <Volume2 :size="14" /><span><small>{{ tr('旁白声音') }}</small><strong>{{ narratorVoice?.nickname || tr('选择旁白音色') }}</strong></span>
                </button>
              </template>
              <template v-else>
                <strong>{{ projectStrategyView?.name || projectView.storyboardStrategy }}</strong><p>{{ projectStrategyView?.description || projectView.storyboardSetting }}</p>
                <div v-if="narrationStrategyActive" class="narrator-voice-summary"><Volume2 :size="13" />{{ tr('旁白音色：') }}{{ narratorVoice?.nickname || tr('未选择') }}</div>
              </template>
            </div>
          </article>
        </div>
      </section>

      <section class="analysis-section">
        <header><h2>{{ tr('全片视听约定') }}</h2></header>
        <article class="profile-card audiovisual-card">
          <div v-if="editing && projectDraft">
            <textarea v-model="projectDraft.audiovisualGuidance" :aria-label="tr('全片视听约定')" :placeholder="tr('按剧情决定')" maxlength="4000" rows="3" />
          </div>
          <div v-else><p>{{ projectView.audiovisualGuidance }}</p></div>

        </article>
      </section>

      </div>
      <div class="production-controls">
        <label class="shot-duration-control">
          <span class="production-control-label"><Timer :size="16" aria-hidden="true" />{{ tr('单分镜最长时长') }}</span>
          <input type="range" min="1" max="30" step="1" :value="durationSeconds"
            :style="{ '--filled': ((durationSeconds - 1) / 29 * 100) + '%' }"
            :aria-label="tr('单分镜最长时长')" :aria-valuetext="durationSeconds + 's'"
            :aria-busy="savingDuration" :disabled="!canEdit || savingEdits || savingDuration"
            @input="previewDuration" @change="commitDuration" />
          <output class="duration-value"><span :key="durationSeconds">{{ durationSeconds }}s</span></output>
        </label>
        <label class="storyboard-switch-row">
          <span class="production-control-label"><GalleryHorizontalEnd :size="16" aria-hidden="true" />{{ tr('逐镜线稿故事版') }}</span>
          <button class="storyboard-switch" type="button" role="switch" :aria-label="tr('逐镜线稿故事版')"
            :aria-checked="storyboardEnabled" :aria-busy="savingStoryboard"
            :disabled="!canEdit || savingEdits || savingStoryboard" @click="toggleStoryboard">
            <span class="switch-track" aria-hidden="true"><span class="switch-thumb" /></span>
          </button>
        </label>
      </div>
      <section class="analysis-section episode-section">
        <header>
          <h2>{{ tr('分集剧情') }}</h2>
          <div v-if="canEdit && !editing" class="episode-actions">
            <AppButton variant="secondary" size="sm" :disabled="episodeBusy" @click="addEpisode">{{ tr('新增一集') }}</AppButton>
            <AppButton v-if="selectedEpisodeBrief" variant="ghost" size="sm" :disabled="episodeBusy" @click="removeEpisode">{{ tr('删除本集') }}</AppButton>
          </div>
        </header>
        <div v-if="!chapters.length && !chaptersLoading" class="episode-empty-state">
          <p>{{ tr('新增一集开始写剧本，也可以和创作助手一起构思。') }}</p>
          <AppButton v-if="canEdit" variant="soft" size="sm" @click="useCreationAgentWorkspace().editTargets(projectId, 0, [])">{{ tr('与助手开始创作') }}</AppButton>
        </div>
        <div ref="episodeTabs" class="episode-tabs" role="tablist" :aria-label="tr('分集剧情')" tabindex="0">
          <AppButton v-for="chapter in chapters" :key="chapter.id" variant="soft" size="sm" icon-only type="button" role="tab" :active="activeEpisode === chapter.number" :aria-selected="activeEpisode === chapter.number" @click="selectEpisode(chapter.number, $event)">{{ chapter.number }}</AppButton>
          <span v-if="chaptersHasMore" class="episode-load-more">{{ chaptersLoading ? tr('加载中…') : tr('继续滚动加载') }}</span>
        </div>
        <div ref="episodeSentinel" class="episode-sentinel" aria-hidden="true"></div>
        <article v-if="selectedEpisode" class="episode-content">
          <header>
            <div>
              <label v-if="editing && selectedEpisodeDraft" class="chapter-title-editor">
                <span>{{ tr('第') }} {{ selectedEpisode.number }} {{ tr('集') }}</span>
                <input v-model="selectedEpisodeDraft.name" :aria-label="tr('章节标题')" maxlength="255" />
              </label>
              <h3 v-else>{{ episodeDisplayLabel(selectedEpisode) }}</h3>
            </div>
          </header>
          <div class="episode-doc-tools">
            <div class="episode-doc-tabs" :aria-label="tr('分集剧情')" role="group">
              <button type="button" :aria-pressed="episodeView === 'source'" @click="episodeViews[selectedEpisode.id] = 'source'">{{ tr('原文') }}</button>
              <button type="button" :aria-pressed="episodeView === 'screenplay'" @click="episodeViews[selectedEpisode.id] = 'screenplay'">{{ tr('导演剧本') }}</button>
            </div>
            <EpisodePacingDialog v-if="canEdit" :key="selectedEpisode.id"
              :pacing="selectedEpisode.episode_pacing" :episode="episodeDisplayLabel(selectedEpisode)"
              :disabled="editing || selectedEpisodeLoading || generatingScripts[selectedEpisode.id]"
              :save="(pacing) => saveEpisodePacing(selectedEpisode!.id, pacing)" />
            <div v-if="canEdit" class="episode-adaptation-controls">
              <AppSelect v-model="analysisModelId" density="compact" :ariaLabel="tr('剧情分析模型')"
                :options="[{ value: '', label: loadingAnalysisModels ? tr('正在读取模型…') : analysisModels.length ? tr('选择分析模型') : tr('无可用模型') }, ...analysisModels]"
                :disabled="!analysisModels.length || analysisRunning || startingAnalysis || adapting || editing" />
              <small v-if="analysisModelsError" class="cover-generation-error" role="alert">{{ analysisModelsError }}</small>
              <AppButton v-if="analysisModelsError" variant="ghost" size="xs" @click="loadAnalysisModels">{{ tr('重试') }}</AppButton>
            <AppButton v-if="canEdit && selectedEpisode.content?.trim()" class="generate-screenplay" variant="primary" size="sm"
              :disabled="editing || !analysisModelId" :title="editing ? tr('请先保存或取消编辑') : undefined" :loading="generatingScripts[selectedEpisode.id]" @click="generateScreenplay(selectedEpisode.id)">
              {{ generatingScripts[selectedEpisode.id] ? tr('正在改编…') : selectedEpisode.screenplay ? tr('重新生成本集剧本') : tr('生成本集剧本') }}
            </AppButton>
            </div>
          </div>
          <div class="episode-document">
          <p v-if="selectedEpisodeLoading" class="episode-content-state">{{ tr('正在加载章节正文…') }}</p>
          <template v-else-if="episodeView === 'source'">
            <textarea v-if="editing && selectedEpisodeDraft" v-model="selectedEpisodeDraft.content" class="chapter-content-editor" :aria-label="tr('章节内容')" />
            <p v-else-if="selectedEpisode.content">{{ selectedEpisode.content }}</p>
            <p v-else class="episode-content-state">{{ tr('本集未提供原文') }}</p>
          </template>
          <template v-else>
            <textarea v-if="editing && selectedEpisodeDraft" v-model="selectedEpisodeDraft.screenplay" class="chapter-content-editor" :aria-label="tr('导演剧本')" />
            <EpisodeScreenplay v-else-if="selectedEpisode.screenplay" :text="selectedEpisode.screenplay" :episode-number="selectedEpisode.number" :episode-name="selectedEpisode.name" />
            <p v-else class="episode-content-state">{{ tr('本集暂无导演剧本') }}</p>
          </template>
          </div>
          <footer><span><UsersRound :size="14" />{{ selectedEpisodeCharacters }}</span><span>{{ tr('第') }} {{ selectedEpisode.number }} {{ tr('章') }}</span></footer>
        </article>
      </section>

      <AppButton v-if="selectedEpisodeBrief" class="continue-button" variant="primary" size="lg" block type="button" @click="continueToSettings"><span><Sparkles :size="18" />{{ tr('进入资产设定') }}</span><ArrowRight :size="18" /></AppButton>
      </template>
      </section>
    <AudioReferencePicker :open="narratorPickerOpen" :selected-id="projectDraft?.narratorAudioReferenceId || novel?.narrator_audio_reference_id" :novel-id="novel?.id" @close="narratorPickerOpen = false" @choose="selectNarratorVoice" />
  </ShortDramaWorkspaceShell>
  </main>
</template>

<style scoped>
.episode-project-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 14px; color: var(--app-text-secondary); font-size: 12px; }
.episode-project-meta > span, .episode-project-meta > label { display: inline-flex; align-items: center; gap: 6px; }
.episode-project-meta svg { flex: none; }
.episode-project-meta :deep(.app-select) { width: auto; }
.tag-editor textarea { width: 100%; box-sizing: border-box; padding: 8px 10px; resize: vertical; border: 1px solid var(--app-border); border-radius: 8px; color: var(--app-text); background: var(--app-surface-muted); font: inherit; }
.tag-editor textarea:focus-visible { outline: 2px solid var(--app-accent); }

.episode-empty-state { padding: 20px; border: 1px dashed var(--app-border); border-radius: 12px; color: var(--app-text-secondary); }
.episode-empty-state p { margin: 0 0 12px; line-height: 1.7; }
.episode-adaptation-controls { display: inline-flex; align-items: center; gap: 8px; max-width: 100%; flex-wrap: wrap; }
.episode-doc-tools { display:flex; align-items:center; justify-content:flex-start; flex-wrap:wrap; gap:10px; margin:12px 0 18px; }
.episode-doc-tabs { display:inline-flex; padding:3px; background:var(--app-surface-muted); border:1px solid var(--app-border); border-radius:9px; }
.episode-doc-tabs button { border:0; background:transparent; color:var(--app-text-secondary); padding:6px 14px; border-radius:6px; cursor:pointer; font:inherit; font-size:13px; }
.episode-doc-tabs button[aria-pressed="true"] { background:var(--app-surface); color:var(--app-accent); box-shadow:0 1px 3px #0002; }
.episode-doc-tabs button:hover { color:var(--app-accent); }
.episode-doc-tabs button:focus-visible { outline:2px solid var(--app-accent); }

.episode-actions { display: flex; gap: 8px; }
.profile-card input[type="checkbox"] { width: auto; min-height: 0; height: auto; accent-color: var(--app-accent); }
.creation-cover-notice p { margin: 0; overflow-wrap: anywhere; }
.creation-cover-notice { padding: 13px 16px; border: 1px solid var(--app-border); border-radius: 12px; background: var(--app-surface); color: var(--app-text-secondary); font-size: 12px; line-height: 1.8; }
@container creation-workspace (max-width: 800px) { .agent-content { padding: 20px 18px; }.analysis-hero { gap: 18px; }.profile-grid { grid-template-columns: 1fr; } }

.agent-page { min-width: 0; min-height: 100%; overflow-x: clip; color: #303442; background: #f9fafc; }
.analysis-hero-copy p { display: flex; align-items: center; gap: 7px; color: #9297a6; font-size: 10px; }
.analysis-hero-copy i { width: 1px; height: 10px; background: #dfe1e8; }
.agent-content { width: min(1440px, 100%); min-width: 0; margin: 0 auto; padding: 20px 22px 48px; box-sizing: border-box; }
.analysis-hero { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 16px; padding: 16px; border-radius: 14px; background: #fff; box-shadow: 0 18px 52px rgb(42 46 64 / 8%); }
.analysis-hero-copy { display: grid; justify-items: start; }
.analysis-ready { margin-bottom: 9px; }
.status-spinner { animation: status-spin 1.1s linear infinite; }
@keyframes status-spin { to { transform: rotate(360deg); } }
.analysis-hero h1 { margin: 0 0 10px; color: #282c3a; font-size: clamp(20px, 2vw, 24px); letter-spacing: -.035em; }
.analysis-title-input { width: min(620px, 100%); margin: 0 0 10px; padding: 5px 9px; color: var(--app-text); font-size: clamp(20px, 2vw, 24px); font-weight: 700; letter-spacing: -.035em; }
.analysis-hero-copy p { margin: 0; font-size: 11px; }
.genre-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 16px; }
.tag-editor { display: grid; width: min(620px, 100%); gap: 5px; margin-top: 13px; }
.tag-editor > span { color: #777c8d; font-size: 9px; font-weight: 650; }
.cover-generation-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.cover-generation-error { flex-basis: 100%; color: var(--creation-danger); }
.analysis-hero-actions { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 8px; }
.secondary-action { display: inline-flex; min-height: 36px; align-items: center; justify-content: center; gap: 7px; padding: 0 12px; border: 0; border-radius: 9px; color: #626879; background: #f3f4f8; cursor: pointer; font-size: 11px; }
.secondary-action:hover { color: #4f51e8; background: #ededff; }
.secondary-action:disabled { opacity: .55; cursor: wait; }
.secondary-action.compact { min-height: 34px; }
.analysis-progress-card { display: grid; grid-template-columns: 52px minmax(0, 1fr) auto; align-items: center; gap: 16px; margin-top: 22px; padding: 20px; border-radius: 16px; background: var(--app-surface); box-shadow: 0 10px 34px rgb(45 49 68 / 6%); }
.analysis-progress-card > span { display: grid; width: 52px; height: 52px; place-items: center; border-radius: 14px; color: var(--app-accent); background: var(--app-accent-soft); }
.analysis-progress-card h2 { margin: 0 0 6px; font-size: 15px; }
.analysis-progress-card p { margin: 0; color: var(--app-text-secondary); font-size: 11px; line-height: 1.7; }
.analysis-progress-card > button { min-height: 36px; padding: 0 15px; border: 0; border-radius: 9px; color: #fff; background: #5b5cf6; cursor: pointer; font-size: 11px; font-weight: 650; }
.analysis-progress-card.is-failed > span { color: var(--creation-danger); background: color-mix(in srgb, var(--creation-danger) 10%, var(--app-surface)); }
.analysis-section { padding-top: 20px; }
.analysis-section > header { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 10px; }
.analysis-section > header > div:not(.episode-actions) { display: grid; gap: 4px; }
.analysis-section > header h2 { margin: 0; color: #303442; font-size: 17px; }
.analysis-section > header p { margin: 2px 0 0; color: #9297a7; font-size: 11px; }
.analysis-section > header > span { color: #999eac; font-size: 10px; }
.analysis-section > header > a { display: inline-flex; align-items: center; gap: 5px; color: #5b5cf6; font-size: 11px; }
.section-kicker { color: #7779ef; font-size: 8px; font-weight: 750; letter-spacing: .16em; }
.profile-grid { display: grid; grid-template-columns: 1fr; gap: 12px; }
.profile-card { display: grid; grid-template-columns: 42px minmax(0, 1fr); gap: 13px; padding: 16px; border-radius: 14px; background: #fff; box-shadow: 0 7px 24px rgb(45 49 68 / 5%); }
.production-settings > section { display: flex; flex-direction: column; }
.production-settings .profile-card { flex: 1; box-sizing: border-box; }
.production-settings > section > header { height: 44px; flex: 0 0 44px; align-items: center; }
.production-controls {
  display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-top: 8px;
  color: var(--app-text); font-size: 13px;
}
.shot-duration-control, .storyboard-switch-row {
  min-width: 0; min-height: 48px; box-sizing: border-box; padding: 4px 16px;
  display: grid; align-items: center; gap: 10px;
  border-radius: 10px; border: 1px solid var(--app-border);
  background: color-mix(in srgb, var(--app-surface) 65%, var(--app-surface-muted));
}
.shot-duration-control { grid-template-columns: minmax(max-content, 1fr) minmax(64px, 160px) auto; }
.storyboard-switch-row { grid-template-columns: 1fr auto; }
.production-control-label { display: inline-flex; align-items: center; gap: 9px; font-weight: 600; }
.production-control-label svg { flex: none; color: var(--app-text-secondary); }
.shot-duration-control input {
  appearance: none; width: 100%; min-width: 0; height: 36px; margin: 0; border: 0; border-radius: 5px; cursor: pointer;
  background: linear-gradient(to right, var(--app-accent) var(--filled), var(--app-border-strong) var(--filled)) center / 100% 4px no-repeat;
}
.shot-duration-control input::-webkit-slider-thumb {
  appearance: none; width: 14px; height: 14px; border: 3px solid var(--app-accent); border-radius: 50%; background: var(--app-surface);
  transition: transform 150ms ease, box-shadow 150ms ease;
}
.shot-duration-control input::-moz-range-thumb {
  box-sizing: border-box; width: 14px; height: 14px; border: 3px solid var(--app-accent); border-radius: 50%; background: var(--app-surface);
  transition: transform 150ms ease;
}
.shot-duration-control input:enabled:is(:hover,:active)::-webkit-slider-thumb { transform: scale(1.15); box-shadow: 0 0 0 4px color-mix(in srgb, var(--app-accent) 15%, transparent); }
.shot-duration-control input:enabled:is(:hover,:active)::-moz-range-thumb { transform: scale(1.15); }
.duration-value {
  display: grid; place-items: center; min-width: 4ch; padding: 3px 6px; border-radius: 6px; font-weight: 650;
  color: var(--app-accent); background: var(--app-accent-soft); font-variant-numeric: tabular-nums;
}
.duration-value span { animation: duration-tick 140ms ease-out; }
@keyframes duration-tick { from { transform: translateY(2px); opacity: .6; } }
.storyboard-switch { display: grid; place-items: center; padding: 0; width: 44px; height: 40px; background: transparent; border: 0; border-radius: 8px; cursor: pointer; }
.switch-track { display: flex; align-items: center; width: 36px; height: 21px; padding: 3px; box-sizing: border-box; border-radius: 20px; background: var(--app-border-strong); transition: background-color 180ms ease; }
.switch-thumb { width: 15px; height: 15px; border-radius: 50%; background: white; box-shadow: 0 1px 3px #0003; transition: transform 190ms cubic-bezier(.2,.8,.2,1); }
.storyboard-switch[aria-checked="true"] .switch-track { background: var(--app-accent); }
.storyboard-switch[aria-checked="true"] .switch-thumb { transform: translateX(15px); }
.storyboard-switch:enabled:hover .switch-track { box-shadow: 0 0 0 3px color-mix(in srgb, var(--app-accent) 12%, transparent); }
.production-controls :is(input,button):focus-visible { outline: 2px solid var(--app-accent); outline-offset: 2px; }
.production-controls :disabled { opacity: .6; cursor: default; }
@container creation-workspace (max-width: 800px) {
  .production-controls { grid-template-columns: minmax(0, 1fr); gap: 6px; }
}
@container creation-workspace (max-width: 420px) {
  .shot-duration-control, .storyboard-switch-row { padding-inline: 10px; gap: 8px; }
  .shot-duration-control { grid-template-columns: max-content minmax(48px, 1fr) auto; }
}
@media (prefers-reduced-motion: reduce) {
  .switch-track, .switch-thumb { transition: none; }
  .shot-duration-control input::-webkit-slider-thumb { transition: none; }
  .shot-duration-control input::-moz-range-thumb { transition: none; }
  .duration-value span { animation: none; }
}
.production-settings { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.audiovisual-card { grid-template-columns: minmax(0, 1fr); }
.audiovisual-card p, .audiovisual-card small { font-size: 12px; line-height: 1.6; }
@container creation-workspace (max-width: 800px) { .production-settings { grid-template-columns: minmax(0, 1fr); gap: 0; } }
.profile-card > span { display: grid; width: 42px; height: 42px; place-items: center; border-radius: 11px; color: #5b5cf6; background: #eff0ff; }
.profile-card > div { display: grid; gap: 4px; }
.profile-card small { color: #969baa; font-size: 9px; }
.profile-card strong { font-size: 13px; }
.profile-card p { margin: 1px 0 0; color: #858a99; font-size: 10px; line-height: 1.55; }
.narrator-voice-button { display: flex; width: 100%; min-height: 42px; align-items: center; gap: 9px; margin-top: 7px; padding: 7px 10px; border: 1px solid var(--app-border); border-radius: 9px; color: var(--app-accent); background: var(--app-surface-muted); cursor: pointer; text-align: left; }.narrator-voice-button:hover { border-color: var(--app-accent); }.narrator-voice-button > span { display: grid; gap: 2px; }.narrator-voice-button small { color: var(--app-text-secondary); font-size: 8px; }.narrator-voice-button strong { color: var(--app-text); font-size: 10px; }.narrator-voice-summary { display: inline-flex; align-items: center; gap: 6px; margin-top: 6px; color: var(--app-accent); font-size: 9px; }
.analysis-title-input, .tag-editor input, .profile-card input, .profile-card textarea, .chapter-title-editor input, .chapter-content-editor { border: 1px solid var(--app-border); border-radius: 9px; outline: 0; background: var(--app-surface-muted); box-shadow: inset 0 1px 2px rgb(39 43 62 / 3%); box-sizing: border-box; transition: border-color .15s ease, box-shadow .15s ease, background-color .15s ease; }
.analysis-title-input:focus, .tag-editor input:focus, .profile-card input:focus, .profile-card textarea:focus, .chapter-title-editor input:focus, .chapter-content-editor:focus { border-color: var(--app-accent); background: var(--app-surface); box-shadow: 0 0 0 3px var(--app-accent-soft); }
.tag-editor input, .profile-card input, .chapter-title-editor input { width: 100%; min-height: 34px; padding: 0 10px; color: var(--app-text); font-size: 11px; }
.storyboard-strategy-select { width: min(260px, 100%); }
.profile-card textarea { width: 100%; min-height: 68px; padding: 8px 10px; resize: vertical; color: var(--app-text-secondary); font: inherit; font-size: 10px; line-height: 1.6; }
.character-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.character-card { display: grid; gap: 12px; padding: 17px; border-radius: 14px; background: #fff; box-shadow: 0 7px 24px rgb(45 49 68 / 5%); }
.character-title { display: flex; align-items: center; gap: 11px; }
.character-title > span { display: grid; width: 38px; height: 38px; place-items: center; border-radius: 50%; color: var(--character-accent); background: color-mix(in srgb, var(--character-accent) 12%, white); font-size: 13px; font-weight: 700; }
.character-title h3 { margin: 0 0 3px; font-size: 13px; }
.character-title small, .episode-appearances small { color: #979cab; font-size: 9px; }
.character-card > p { margin: 0; color: #707687; font-size: 11px; line-height: 1.7; }
.episode-appearances { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; padding-top: 4px; }
.episode-appearances small { margin-right: 3px; }
.show-more { display: flex; width: 100%; min-height: 35px; align-items: center; justify-content: center; gap: 6px; margin-top: 10px; border: 0; border-radius: 9px; color: #777c8c; background: transparent; cursor: pointer; font-size: 10px; }
.show-more:hover { background: #f1f2f6; }
.show-more svg { transition: transform .15s ease; }
.show-more svg.is-up { transform: rotate(180deg); }
.episode-section { min-width: 0; }
.episode-tabs { display: flex; width: 100%; max-width: 100%; gap: 7px; margin-bottom: 10px; padding: 2px 2px 8px; overflow-x: auto; overflow-y: hidden; overscroll-behavior-x: contain; scroll-behavior: smooth; scroll-snap-type: x proximity; scrollbar-color: #d9dbe6 transparent; scrollbar-width: thin; }
.episode-tabs::-webkit-scrollbar { height: 5px; }
.episode-tabs::-webkit-scrollbar-track { background: transparent; }
.episode-tabs::-webkit-scrollbar-thumb { border-radius: 999px; background: #d9dbe6; }
.episode-tabs:focus-visible { outline: 3px solid rgb(91 92 246 / 14%); outline-offset: 2px; border-radius: 10px; }
.episode-tabs button { display: grid; width: 34px; min-width: 34px; height: 34px; flex: 0 0 34px; place-items: center; scroll-snap-align: center; border: 0; border-radius: 9px; color: #777d8e; background: #f1f2f7; cursor: pointer; font-size: 11px; }
.episode-tabs button.is-active { color: #fff; background: #6768ef; box-shadow: 0 7px 18px rgb(91 92 246 / 20%); }
.episode-content { scroll-margin-top: calc(var(--short-drama-header-height, 72px) + 12px); --reading-inset: clamp(16px, 3vw, 40px); min-width: 0; border: 1px solid var(--app-border); border-radius: 14px; background: var(--app-surface); }
.episode-content > header { padding: 22px var(--reading-inset) 0; }
.episode-content h3 { margin: 0; color: var(--app-text); font-size: 20px; letter-spacing: -.02em; }
.episode-content .episode-doc-tools { margin: 0; padding: 12px var(--reading-inset) 16px; border-bottom: 1px solid var(--app-border); }
.episode-document { padding: clamp(18px, 2vw, 30px) var(--reading-inset); }
.chapter-title-editor { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: center; gap: 8px; margin-top: 5px; }
.chapter-title-editor > span { color: #555b6b; font-size: 12px; font-weight: 700; white-space: nowrap; }
.episode-document > p { max-width: 52em; margin: 0 auto; color: var(--app-text); font-size: 15px; line-height: 2; overflow-wrap: anywhere; white-space: pre-wrap; }
.episode-document > p.episode-content-state { min-height: 100px; display: grid; place-items: center; color: var(--app-text-secondary); }
.chapter-content-editor { display: block; width: 100%; min-height: 520px; margin: 0; padding: 18px 20px; resize: vertical; color: var(--app-text); font: inherit; font-size: 15px; line-height: 2; white-space: pre-wrap; }
.episode-content > footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 11px var(--reading-inset); border-top: 1px solid var(--app-border); border-radius: 0 0 14px 14px; color: var(--app-text-secondary); background: var(--app-surface-muted); font-size: 12px; }
.episode-content > footer span { display: inline-flex; align-items: center; gap: 5px; }
.episode-sentinel { height: 2px; margin-top: 8px; }
.episode-load-more { align-self: center; padding: 0 8px; color: var(--app-text-muted); font-size: 11px; white-space: nowrap; }
.continue-button { position: relative; display: flex; width: 100%; min-height: 52px; align-items: center; justify-content: center; margin-top: 28px; padding: 0 52px; border: 0; border-radius: 13px; color: #fff; background: #5b5cf6; box-shadow: 0 14px 30px rgb(91 92 246 / 22%); cursor: pointer; font-size: 13px; font-weight: 700; }
.continue-button > span { display: inline-flex; align-items: center; gap: 8px; }
.continue-button > svg { position: absolute; right: 20px; }
.continue-button:hover { background: #4d4ee9; transform: translateY(-1px); }
@media (max-width: 960px) {
  .analysis-hero { grid-template-columns: auto minmax(0, 1fr); }
  .analysis-hero > .analysis-hero-actions { grid-column: 2; justify-self: start; }
}
@media (max-width: 720px) {
  .agent-content { width: 100%; padding: 22px 14px 60px; }
  .analysis-hero { grid-template-columns: auto minmax(0, 1fr); gap: 15px; padding: 15px; }
  .analysis-hero h1 { font-size: 19px; }
  .genre-tags { margin-top: 11px; }
  .profile-grid, .character-grid { grid-template-columns: 1fr; }
  .analysis-section { padding-top: 20px; }
  .analysis-progress-card { grid-template-columns: 44px minmax(0, 1fr); }
  .analysis-progress-card > span { width: 44px; height: 44px; }
  .analysis-progress-card > button { grid-column: 2; justify-self: start; }
  .episode-content > footer { align-items: flex-start; flex-direction: column; }
}
@media (max-width: 480px) {
  .analysis-hero { grid-template-columns: 1fr; }
  .analysis-hero > .analysis-hero-actions { grid-column: 1; flex-wrap: wrap; justify-self: stretch; }
  .analysis-section > header { align-items: flex-start; flex-direction: column; }
}
</style>
