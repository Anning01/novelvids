<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  BookOpenText,
  Boxes,
  Check,
  Clapperboard,
  ImagePlus,
  Layers3,
  LoaderCircle,
  Merge as MergeIcon,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
  Upload,
  UsersRound,
} from 'lucide-vue-next'
import AppBadge from '@/components/AppBadge.vue'
import AssetCreateDialog from '@/components/AssetCreateDialog.vue'
import AssetBatchGenerateDialog from '@/components/AssetBatchGenerateDialog.vue'
import ShortDramaWorkspaceShell from '@/components/ShortDramaWorkspaceShell.vue'
import { api, sleep, statusLabel } from '@/api'
import { appConfirm } from '@/shared/confirmDialog'
import { notice } from '@/shared/notice'
import { readShortDramaSettings } from '@/shared/shortDramaProject'
import { AssetTypeEnum, TaskStatusEnum, type AiTask, type Asset, type Chapter } from '@/types'

type AssetTab = 'character' | 'scene' | 'prop'
type AssetScope = 'project' | 'chapter'

interface ManualProjectMeta {
  projectId?: number
  name: string
  aspectRatio: string
  resolution: string
  style: string
  creationMode: 'agent' | 'manual'
}

const fallbackProject: ManualProjectMeta = {
  name: '新项目',
  aspectRatio: '9:16',
  resolution: '720p',
  style: '写实通用',
  creationMode: 'manual',
}

function readProjectMeta(): ManualProjectMeta {
  try {
    const stored = sessionStorage.getItem('short-drama-manual-project')
    return stored ? { ...fallbackProject, ...JSON.parse(stored) } : fallbackProject
  } catch {
    return fallbackProject
  }
}

const route = useRoute()
const router = useRouter()
const projectId = computed(() => Number(route.params.projectId))
const selectedChapterId = computed(() => Number(route.query.chapter))
const project = ref(readProjectMeta())
const chapters = ref<Chapter[]>([])
const selectedChapter = ref<Chapter | null>(null)
const assets = ref<Asset[]>([])
const activeTab = ref<AssetTab>('character')
const assetScope = ref<AssetScope>('project')
const editingName = ref(false)
const nameDraft = ref('')
const loading = ref(true)
const showAssetDialog = ref(false)
const editingAsset = ref<Asset | null>(null)
const assetDrawerMode = ref<'ai' | 'library' | 'upload'>('ai')
const showBatchDialog = ref(false)
const batchGenerating = ref(false)
const submittingExtraction = ref(false)
const extractionTask = ref<AiTask | null>(null)
const extractionSubmissionError = ref('')
const generatingAssetIds = ref(new Set<number>())
const failedAssetIds = ref(new Set<number>())
const mergingAssetIds = ref(new Set<number>())
const draggingAssetId = ref<number | null>(null)
const mergeHoverTargetId = ref<number | null>(null)
const mergeArmedTargetId = ref<number | null>(null)
const mergeProgressKey = ref(0)
let pageAlive = true
let extractionPollVersion = 0
let mergeHoverTimer: ReturnType<typeof setTimeout> | null = null
let suppressAssetClickUntil = 0

const terminalTaskStatuses = new Set([
  TaskStatusEnum.COMPLETED,
  TaskStatusEnum.FAILED,
  TaskStatusEnum.CANCELLED,
])

const tabs = [
  { value: 'character' as const, label: '角色', icon: UsersRound, type: AssetTypeEnum.PERSON },
  { value: 'scene' as const, label: '场景', icon: ImagePlus, type: AssetTypeEnum.SCENE },
  { value: 'prop' as const, label: '道具', icon: Boxes, type: AssetTypeEnum.ITEM },
]

const activeTabConfig = computed(() => tabs.find(item => item.value === activeTab.value) ?? tabs[0])
const visibleAssets = computed(() => assets.value.filter(item => item.asset_type === activeTabConfig.value.type))
const completedCount = computed(() => visibleAssets.value.filter(item => item.main_image).length)
const generatingCount = computed(() => visibleAssets.value.filter(item => generatingAssetIds.value.has(item.id)).length)
const failedCount = computed(() => visibleAssets.value.filter(item => failedAssetIds.value.has(item.id)).length)
const draggingAsset = computed(() => assets.value.find(item => item.id === draggingAssetId.value) ?? null)
const mergeTargetAsset = computed(() => assets.value.find(item => item.id === mergeHoverTargetId.value) ?? null)
const mergeDataAsset = computed(() => {
  const source = draggingAsset.value
  const target = mergeTargetAsset.value
  if (!source || !target) return null
  const rank = (asset: Asset) => [
    asset.last_updated_chapter ?? -1,
    Date.parse(asset.updated_at || '') || 0,
    asset.id,
  ]
  const sourceRank = rank(source)
  const targetRank = rank(target)
  for (let index = 0; index < sourceRank.length; index++) {
    if (sourceRank[index] !== targetRank[index]) {
      return sourceRank[index] > targetRank[index] ? source : target
    }
  }
  return target
})
const mergeImageCount = computed(() => {
  const urls = new Set<string>()
  for (const asset of [draggingAsset.value, mergeTargetAsset.value]) {
    if (!asset) continue
    for (const image of [asset.main_image, asset.angle_image_1, asset.angle_image_2]) {
      if (image) urls.add(image)
    }
  }
  return urls.size
})
const extractionTaskActive = computed(() => {
  const status = extractionTask.value?.status
  return status === TaskStatusEnum.PENDING || status === TaskStatusEnum.PROCESSING || status === TaskStatusEnum.QUEUED
})
const extractionBusy = computed(() => submittingExtraction.value || extractionTaskActive.value)
const extractionStatusVisible = computed(() => {
  if (extractionTask.value?.status === TaskStatusEnum.COMPLETED) return false
  return submittingExtraction.value
    || extractionTaskActive.value
    || Boolean(extractionSubmissionError.value)
    || extractionTask.value?.status === TaskStatusEnum.FAILED
    || extractionTask.value?.status === TaskStatusEnum.CANCELLED
})
const extractionStatusText = computed(() => (
  extractionSubmissionError.value
    ? '提交失败'
    : submittingExtraction.value && !extractionTask.value
      ? '提交中'
    : statusLabel(extractionTask.value?.status)
))
const extractionStatusMessage = computed(() => {
  if (extractionSubmissionError.value) return extractionSubmissionError.value
  const task = extractionTask.value
  if (!task) return submittingExtraction.value ? '正在创建本章资产提取任务。' : ''
  if (task.status === TaskStatusEnum.PENDING) return '任务已提交，正在等待模型执行。'
  if (task.status === TaskStatusEnum.QUEUED) return '任务正在队列中等待处理。'
  if (task.status === TaskStatusEnum.PROCESSING) return '正在分析本章人物、场景和道具，并与项目资产增量合并。'
  if (task.status === TaskStatusEnum.CANCELLED) return '任务已取消，可以重新提取本章资产。'
  return extractionErrorMessage(new Error(task.error_message || '本章资产提取失败'))
})
const extractionStatusClass = computed(() => ({
  'is-running': extractionTaskActive.value || submittingExtraction.value,
  'is-error': Boolean(extractionSubmissionError.value)
    || extractionTask.value?.status === TaskStatusEnum.FAILED
    || extractionTask.value?.status === TaskStatusEnum.CANCELLED,
}))

async function loadProject(chapterId = selectedChapterId.value) {
  if (!Number.isFinite(projectId.value) || projectId.value <= 0) return
  loading.value = true
  try {
    const [projectResponse, chapterListResponse] = await Promise.all([
      api.novelMeta(projectId.value),
      api.chapters(projectId.value),
    ])
    if (projectResponse.data.workflow_kind === 'remake') {
      const progress = (await api.remakeProjectProgress(projectId.value)).data
      if (progress.aggregate_status !== 'completed') {
        await router.replace({ name: 'remake-progress', params: { projectId: projectId.value } })
        return
      }
    }
    chapters.value = chapterListResponse.data.items
    const targetChapter = chapters.value.find(item => item.id === chapterId) ?? chapters.value[0] ?? null
    if (targetChapter && targetChapter.id !== selectedChapterId.value) {
      await router.replace({ query: { ...route.query, chapter: String(targetChapter.id) } })
    }
    const scopedChapterId = assetScope.value === 'chapter' ? targetChapter?.id : undefined
    const [assetResponse, chapterResponse, extractionResponse] = await Promise.all([
      api.assets(projectId.value, 1, 100, scopedChapterId),
      targetChapter ? api.chapter(targetChapter.id) : Promise.resolve(null),
      targetChapter ? api.latestExtraction(targetChapter.id) : Promise.resolve(null),
    ])
    const settings = readShortDramaSettings(projectResponse.data)
    project.value = {
      ...project.value,
      projectId: projectResponse.data.id,
      name: projectResponse.data.name,
      aspectRatio: settings.aspectRatio || project.value.aspectRatio,
      resolution: settings.resolution || project.value.resolution,
      style: settings.style || project.value.style,
      creationMode: projectResponse.data.author?.includes('Agent') ? 'agent' : 'manual',
    }
    selectedChapter.value = chapterResponse?.data ?? null
    assets.value = assetResponse.data.items
    extractionTask.value = extractionResponse?.data?.status === TaskStatusEnum.COMPLETED
      ? null
      : extractionResponse?.data ?? null
    extractionSubmissionError.value = ''
    if (extractionTaskActive.value && extractionTask.value) {
      void monitorExtractionTask(extractionTask.value.id)
    }
    // 刷新后恢复仍在生成中的资产参考图状态（spinner + 轮询）
    void resumeActiveGenerations()
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

async function selectChapter(chapter: Chapter) {
  if (chapter.id === selectedChapter.value?.id) return
  extractionPollVersion++
  extractionTask.value = null
  extractionSubmissionError.value = ''
  await router.replace({ query: { ...route.query, chapter: String(chapter.id) } })
  await loadProject(chapter.id)
}

function extractionErrorMessage(error: unknown) {
  const message = (error as Error).message || '本章资产提取失败'
  return /insufficient balance/i.test(message)
    ? '模型余额不足，请充值或切换可用模型后重试'
    : message
}

async function refreshAssets() {
  const chapterId = assetScope.value === 'chapter' ? selectedChapter.value?.id : undefined
  assets.value = (await api.assets(projectId.value, 1, 100, chapterId)).data.items
  if (editingAsset.value) {
    editingAsset.value = assets.value.find(item => item.id === editingAsset.value?.id) || null
  }
}

async function setAssetScope(nextScope: AssetScope) {
  if (nextScope === assetScope.value) return
  const previousScope = assetScope.value
  assetScope.value = nextScope
  loading.value = true
  try {
    await refreshAssets()
  } catch (error) {
    assetScope.value = previousScope
    notice.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

async function monitorExtractionTask(taskId: string, notifyWhenComplete = false) {
  const pollVersion = ++extractionPollVersion
  try {
    let task = extractionTask.value?.id === taskId
      ? extractionTask.value
      : (await api.task(taskId)).data
    extractionTask.value = task
    while (pageAlive && pollVersion === extractionPollVersion && !terminalTaskStatuses.has(task.status)) {
      await sleep(1500)
      task = (await api.task(task.id)).data
      extractionTask.value = task
    }
    if (!pageAlive || pollVersion !== extractionPollVersion) return
    if (task.status === TaskStatusEnum.COMPLETED) {
      extractionTask.value = null
      await refreshAssets()
      if (notifyWhenComplete) notice.success(`第 ${selectedChapter.value?.number || '-'} 章资产提取完成`)
    }
  } catch (error) {
    extractionSubmissionError.value = `任务状态读取失败：${extractionErrorMessage(error)}`
    notice.error(extractionSubmissionError.value)
  }
}

async function extractSelectedChapterAssets() {
  const chapter = selectedChapter.value
  if (!chapter || extractionBusy.value) return
  submittingExtraction.value = true
  extractionSubmissionError.value = ''
  try {
    const task = (await api.extract(chapter.id)).data
    extractionTask.value = task
    await monitorExtractionTask(task.id, true)
  } catch (error) {
    const message = (error as Error).message || ''
    const existingTaskId = message.match(/\(([0-9a-f-]{36})\)/i)?.[1]
    if (existingTaskId) {
      try {
        extractionTask.value = (await api.task(existingTaskId)).data
        await monitorExtractionTask(existingTaskId, true)
        return
      } catch (taskError) {
        extractionSubmissionError.value = extractionErrorMessage(taskError)
      }
    } else {
      extractionSubmissionError.value = extractionErrorMessage(error)
    }
    notice.error(extractionSubmissionError.value)
  } finally {
    submittingExtraction.value = false
  }
}

function startRename() {
  nameDraft.value = project.value.name
  editingName.value = true
}

async function saveName() {
  const nextName = nameDraft.value.trim()
  if (!nextName || nextName === project.value.name) {
    editingName.value = false
    return
  }
  try {
    const response = await api.updateNovel(projectId.value, { name: nextName })
    project.value.name = response.data.name
    editingName.value = false
    notice.success('项目名称已更新')
  } catch (error) {
    notice.error((error as Error).message)
  }
}

function openAssetDialog(asset?: Asset, initialMode: 'ai' | 'library' | 'upload' = 'ai') {
  editingAsset.value = asset || null
  assetDrawerMode.value = initialMode
  showAssetDialog.value = true
}

function closeAssetDialog() {
  showAssetDialog.value = false
  editingAsset.value = null
}

function addCreatedAsset(asset: Asset) {
  assets.value.unshift(asset)
}

function saveEditedAsset(asset: Asset) {
  assets.value = assets.value.map(item => item.id === asset.id ? asset : item)
  if (editingAsset.value?.id === asset.id) editingAsset.value = asset
}

function truncateText(value: string | undefined, maxLength: number) {
  const normalized = value?.trim() || ''
  return normalized.length > maxLength
    ? `${normalized.slice(0, maxLength).trimEnd()}...`
    : normalized
}

async function removeAsset(asset: Asset) {
  if (!await appConfirm({
    title: `删除${activeTabConfig.value.label}「${asset.canonical_name}」？`,
    message: '该资产及其参考图片将被删除，且无法恢复。',
    confirmLabel: `删除${activeTabConfig.value.label}`,
    tone: 'danger',
  })) return
  try {
    await api.deleteAsset(asset.id)
    assets.value = assets.value.filter(item => item.id !== asset.id)
    notice.success('资产已删除')
  } catch (error) {
    notice.error((error as Error).message)
  }
}

function setAssetMerging(assetId: number, value: boolean) {
  const next = new Set(mergingAssetIds.value)
  value ? next.add(assetId) : next.delete(assetId)
  mergingAssetIds.value = next
}

function clearMergeHover(clearSource = false) {
  if (mergeHoverTimer) clearTimeout(mergeHoverTimer)
  mergeHoverTimer = null
  mergeHoverTargetId.value = null
  mergeArmedTargetId.value = null
  if (clearSource) draggingAssetId.value = null
}

function startAssetDrag(event: DragEvent, asset: Asset) {
  if (generatingAssetIds.value.has(asset.id) || mergingAssetIds.value.has(asset.id)) {
    event.preventDefault()
    return
  }
  clearMergeHover(true)
  draggingAssetId.value = asset.id
  suppressAssetClickUntil = Date.now() + 600
  event.dataTransfer?.setData('text/plain', String(asset.id))
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}

function enterMergeTarget(target: Asset) {
  const sourceId = draggingAssetId.value
  if (!sourceId || sourceId === target.id || mergingAssetIds.value.has(target.id)) return
  if (mergeHoverTargetId.value === target.id) return
  clearMergeHover()
  mergeHoverTargetId.value = target.id
  mergeProgressKey.value++
  mergeHoverTimer = setTimeout(() => {
    if (draggingAssetId.value === sourceId && mergeHoverTargetId.value === target.id) {
      mergeArmedTargetId.value = target.id
    }
  }, 2000)
}

function leaveMergeTarget(event: DragEvent, target: Asset) {
  const nextElement = event.relatedTarget
  if (nextElement instanceof Node && event.currentTarget instanceof Node && event.currentTarget.contains(nextElement)) return
  if (mergeHoverTargetId.value === target.id) clearMergeHover()
}

function allowAssetDrop(event: DragEvent, target: Asset) {
  if (!draggingAssetId.value || draggingAssetId.value === target.id) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
}

async function dropAsset(event: DragEvent, target: Asset) {
  event.preventDefault()
  event.stopPropagation()
  const sourceId = draggingAssetId.value || Number(event.dataTransfer?.getData('text/plain'))
  const armed = mergeArmedTargetId.value === target.id
  suppressAssetClickUntil = Date.now() + 600
  clearMergeHover(true)
  if (!sourceId || sourceId === target.id) return
  if (!armed) {
    notice.info('请在目标资产上停留 2 秒，出现“释放合并”后再放手')
    return
  }

  const sourceIndex = assets.value.findIndex(item => item.id === sourceId)
  const targetIndex = assets.value.findIndex(item => item.id === target.id)
  const insertionIndex = targetIndex - (
    sourceIndex >= 0 && sourceIndex < targetIndex ? 1 : 0
  )
  setAssetMerging(sourceId, true)
  setAssetMerging(target.id, true)
  try {
    const result = (await api.mergeAssets(sourceId, target.id)).data
    const remaining = assets.value.filter(item => item.id !== sourceId && item.id !== target.id)
    remaining.splice(Math.min(Math.max(insertionIndex, 0), remaining.length), 0, result.asset)
    assets.value = remaining
    setAssetFailed(sourceId, false)
    setAssetFailed(target.id, false)
    notice.success(result.summary.length ? result.summary.join('，') : '资产已增量合并')
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    setAssetMerging(sourceId, false)
    setAssetMerging(target.id, false)
  }
}

function finishAssetDrag() {
  suppressAssetClickUntil = Date.now() + 600
  clearMergeHover(true)
}

function handleAssetClick(asset: Asset) {
  if (Date.now() < suppressAssetClickUntil || mergingAssetIds.value.has(asset.id)) return
  openAssetDialog(asset)
}

function setAssetGenerating(assetId: number, value: boolean) {
  const next = new Set(generatingAssetIds.value)
  value ? next.add(assetId) : next.delete(assetId)
  generatingAssetIds.value = next
}

function setAssetFailed(assetId: number, value: boolean) {
  const next = new Set(failedAssetIds.value)
  value ? next.add(assetId) : next.delete(assetId)
  failedAssetIds.value = next
}

async function monitorAssetGeneration(assetId: number, taskId: string): Promise<boolean> {
  try {
    let task = (await api.task(taskId)).data
    while (pageAlive && !terminalTaskStatuses.has(task.status)) {
      await sleep(2000)
      task = (await api.task(task.id)).data
    }
    if (!pageAlive) return false
    const completed = task.status === TaskStatusEnum.COMPLETED
    setAssetFailed(assetId, !completed)
    if (completed) await refreshAssets()
    return completed
  } catch {
    setAssetFailed(assetId, true)
    return false
  } finally {
    setAssetGenerating(assetId, false)
  }
}

async function generateAssetAndWait(asset: Asset) {
  setAssetGenerating(asset.id, true)
  setAssetFailed(asset.id, false)
  let taskId: string
  try {
    taskId = (await api.generateAsset(asset.id)).data.id
  } catch {
    setAssetFailed(asset.id, true)
    setAssetGenerating(asset.id, false)
    return false
  }
  return monitorAssetGeneration(asset.id, taskId)
}

async function resumeActiveGenerations() {
  if (!Number.isFinite(projectId.value) || projectId.value <= 0) return
  try {
    const response = await api.activeAssetGenerations(projectId.value)
    for (const item of response.data) {
      if (!assets.value.some(asset => asset.id === item.asset_id)) continue
      setAssetGenerating(item.asset_id, true)
      setAssetFailed(item.asset_id, false)
      void monitorAssetGeneration(item.asset_id, item.task_id)
    }
  } catch (error) {
    notice.error((error as Error).message)
  }
}

async function batchGenerateAssets(options: { assetIds: number[]; modelConfigId: number; concurrency: number; clarity: string; ratio: string; outputFormat: string; generationCount: number }) {
  if (batchGenerating.value) return
  const selected = new Set(options.assetIds)
  const targets = assets.value.filter(asset => selected.has(asset.id) && !asset.main_image && !generatingAssetIds.value.has(asset.id))
  if (!targets.length) return

  showBatchDialog.value = false
  batchGenerating.value = true
  for (const asset of targets) {
    setAssetGenerating(asset.id, true)
    setAssetFailed(asset.id, false)
  }
  try {
    const preparedAssets = await Promise.all(targets.map(async asset => {
      const metadata = {
        ...(asset.metadata || {}),
        model_config_id: options.modelConfigId,
        clarity: options.clarity,
        resolution: options.clarity,
        aspect_ratio: options.ratio,
        output_format: options.outputFormat,
        generation_count: 1,
      }
      const updated = (await api.updateAsset(asset.id, { metadata })).data
      assets.value = assets.value.map(item => item.id === updated.id ? updated : item)
      return updated
    }))
    const concurrency = Math.max(1, Math.min(4, options.concurrency || 1, preparedAssets.length))
    let cursor = 0
    let succeeded = 0
    let failed = 0
    const worker = async () => {
      while (pageAlive) {
        const asset = preparedAssets[cursor++]
        if (!asset) return
        const completed = await generateAssetAndWait(asset)
        completed ? succeeded++ : failed++
      }
    }
    await Promise.all(Array.from({ length: concurrency }, () => worker()))
    if (!pageAlive) return
    await refreshAssets()
    if (failed) notice.info(`批量生成完成：成功 ${succeeded} 个，失败 ${failed} 个`)
    else notice.success(`${succeeded} 个资产设定图已生成`)
  } catch (error) {
    for (const asset of targets) setAssetGenerating(asset.id, false)
    notice.error((error as Error).message)
  } finally {
    batchGenerating.value = false
  }
}

function goToStoryboard() {
  void router.push({
    path: `/create/short-drama/storyboard/${projectId.value}`,
    query: route.query.chapter ? { chapter: String(route.query.chapter) } : undefined,
  })
}

onMounted(loadProject)
watch(activeTab, () => {
  clearMergeHover(true)
})
onBeforeUnmount(() => {
  pageAlive = false
  extractionPollVersion++
  clearMergeHover(true)
})
</script>

<template>
  <main class="manual-page">
    <ShortDramaWorkspaceShell
      :project-id="projectId"
      :project-name="project.name"
      :aspect-ratio="project.aspectRatio"
      :resolution="project.resolution"
      :style-name="project.style"
      active-phase="settings"
      :creation-mode="project.creationMode"
      :chapters="chapters"
      :active-chapter-id="selectedChapter?.id || 0"
      @select-chapter="selectChapter"
    >
      <template #project-name>
        <div class="project-name-line">
            <template v-if="editingName">
              <input v-model="nameDraft" maxlength="80" autofocus @keyup.enter="saveName" @keyup.esc="editingName = false" @blur="saveName" />
            </template>
            <template v-else>
              <strong>{{ project.name }}</strong>
              <AppButton type="button" variant="ghost" size="xs" icon-only aria-label="编辑项目名称" @click="startRename"><Pencil :size="13" /></AppButton>
            </template>
        </div>
      </template>

    <section class="manual-workspace">
      <header class="asset-toolbar">
        <nav aria-label="项目资产类型">
          <AppButton v-for="tab in tabs" :key="tab.value" type="button" variant="ghost" size="sm" :active="activeTab === tab.value" @click="activeTab = tab.value">
            <component :is="tab.icon" :size="17" />{{ tab.label }}
          </AppButton>
        </nav>
        <div class="asset-summary">
          <span v-if="project.creationMode === 'agent'" class="chapter-context"><BookOpenText :size="13" />{{ selectedChapter ? `当前第 ${selectedChapter.number} 章` : '未选择章节' }}</span>
          <div v-if="project.creationMode === 'agent' && selectedChapter" class="asset-scope-switch" role="group" aria-label="资产范围">
            <AppButton type="button" variant="ghost" size="xs" :active="assetScope === 'project'" @click="setAssetScope('project')">全部项目</AppButton>
            <AppButton type="button" variant="ghost" size="xs" :active="assetScope === 'chapter'" @click="setAssetScope('chapter')">当前章节</AppButton>
          </div>
          <AppButton
            v-if="project.creationMode === 'agent'"
            type="button"
            variant="secondary"
            size="sm"
            :loading="extractionBusy"
            :disabled="!selectedChapter || extractionBusy"
            aria-label="提取本章资产"
            :title="selectedChapter ? `提取第 ${selectedChapter.number} 章资产` : '请先在剧本阶段选择章节'"
            @click="extractSelectedChapterAssets"
          >
            <Boxes v-if="!extractionBusy" :size="15" />
            {{ extractionBusy ? '正在提取本章' : '提取本章资产' }}
          </AppButton>
          <i v-if="project.creationMode === 'agent'" />
          <span>{{ activeTabConfig.label }}总计 <strong>{{ visibleAssets.length }}</strong></span>
          <i />
          <span><Check :size="13" />已完成 {{ completedCount }}</span>
          <span><i v-if="generatingCount" class="generating-summary-dot" />生成中 {{ generatingCount }}</span>
          <span>失败 {{ failedCount }}</span>
          <AppButton type="button" variant="secondary" size="sm" icon-only aria-label="刷新" @click="refreshAssets"><RefreshCw :size="14" /></AppButton>
          <AppButton type="button" variant="primary" size="sm" @click="openAssetDialog()"><Plus :size="15" />添加{{ activeTabConfig.label }}</AppButton>
          <AppButton type="button" variant="soft" size="sm" :loading="batchGenerating" :disabled="batchGenerating" @click="assets.length ? showBatchDialog = true : notice.info('请先添加角色、场景或道具资产')"><Layers3 v-if="!batchGenerating" :size="15" />{{ batchGenerating ? '批量生成中' : '批量生成' }}</AppButton>
        </div>
      </header>

      <div
        v-if="project.creationMode === 'agent' && extractionStatusVisible"
        class="extraction-task-status"
        :class="extractionStatusClass"
        role="status"
        aria-live="polite"
      >
        <span>
          <LoaderCircle v-if="extractionBusy" :size="19" />
          <RefreshCw v-else :size="19" />
        </span>
        <div>
          <strong>第 {{ selectedChapter?.number || '-' }} 章资产提取 · {{ extractionStatusText }}</strong>
          <p>{{ extractionStatusMessage }}</p>
          <small v-if="extractionTask">任务 ID：{{ extractionTask.id }}</small>
        </div>
      </div>

      <div v-if="loading" class="workspace-state"><RefreshCw class="is-spinning" :size="28" /><span>正在加载项目…</span></div>
      <div v-else-if="!visibleAssets.length" class="workspace-state empty-state">
        <span class="empty-icon"><component :is="activeTabConfig.icon" :size="32" /></span>
        <strong>暂无{{ activeTabConfig.label }}</strong>
        <p>添加第一个{{ activeTabConfig.label }}，开始搭建你的短剧世界。</p>
        <AppButton type="button" variant="primary" size="sm" @click="openAssetDialog()"><Plus :size="15" />添加{{ activeTabConfig.label }}</AppButton>
      </div>
      <div v-else class="asset-grid">
        <article
          v-for="asset in visibleAssets"
          :key="asset.id"
          class="asset-card"
          :class="{
            'is-drag-source': draggingAssetId === asset.id,
            'is-merge-target': mergeHoverTargetId === asset.id,
            'is-merge-armed': mergeArmedTargetId === asset.id,
            'is-merging': mergingAssetIds.has(asset.id),
          }"
          :draggable="!generatingAssetIds.has(asset.id) && !mergingAssetIds.has(asset.id)"
          :aria-grabbed="draggingAssetId === asset.id"
          @dragstart="startAssetDrag($event, asset)"
          @dragenter.prevent="enterMergeTarget(asset)"
          @dragover="allowAssetDrop($event, asset)"
          @dragleave="leaveMergeTarget($event, asset)"
          @drop="dropAsset($event, asset)"
          @dragend="finishAssetDrag"
        >
          <button class="asset-card-open" type="button" :aria-label="`查看并编辑${activeTabConfig.label}：${asset.canonical_name}`" @click="handleAssetClick(asset)">
            <div class="asset-visual" :class="{ 'is-generating': generatingAssetIds.has(asset.id), 'is-empty': !asset.main_image }">
              <div v-if="generatingAssetIds.has(asset.id)" class="asset-generating-placeholder" role="status" aria-live="polite">
                <span><LoaderCircle :size="24" /></span>
                <strong>正在生成参考图</strong>
                <small>完成后将在这里自动显示</small>
              </div>
              <img
                v-else-if="asset.main_image"
                :src="asset.main_image_thumbnail || asset.main_image"
                :alt="asset.canonical_name"
                loading="lazy"
                decoding="async"
              />
              <component v-else :is="activeTabConfig.icon" :size="30" />
              <AppBadge v-if="generatingAssetIds.has(asset.id)" class="asset-state-badge is-running" tone="accent" size="sm"><LoaderCircle :size="12" />生成中</AppBadge>
              <AppBadge v-else-if="failedAssetIds.has(asset.id)" class="asset-state-badge" tone="danger" size="sm">生成失败</AppBadge>
              <div v-if="!generatingAssetIds.has(asset.id)" class="asset-card-info">
                <strong>{{ truncateText(asset.canonical_name, 16) }}</strong>
                <p>{{ truncateText(asset.description || `尚未填写${activeTabConfig.label}描述`, 32) }}</p>
              </div>
            </div>
          </button>
          <div class="asset-card-actions" aria-label="资产操作">
            <AppButton class="asset-card-action" type="button" variant="ghost" size="xs" icon-only data-tooltip="编辑" title="编辑" :disabled="mergingAssetIds.has(asset.id)" :aria-label="`编辑${asset.canonical_name}`" @click="openAssetDialog(asset)"><Pencil :size="14" /></AppButton>
            <AppButton class="asset-card-action" type="button" variant="ghost" size="xs" icon-only data-tooltip="本地上传" title="本地上传" :disabled="mergingAssetIds.has(asset.id)" :aria-label="`为${asset.canonical_name}本地上传图片`" @click="openAssetDialog(asset, 'upload')"><Upload :size="14" /></AppButton>
            <AppButton class="asset-card-action is-danger" type="button" variant="ghost" size="xs" icon-only data-tooltip="删除" title="删除" :disabled="mergingAssetIds.has(asset.id)" :aria-label="`删除${asset.canonical_name}`" @click="removeAsset(asset)"><Trash2 :size="14" /></AppButton>
          </div>
          <div
            v-if="mergeHoverTargetId === asset.id"
            :key="mergeProgressKey"
            class="asset-merge-overlay"
            aria-hidden="true"
          >
            <span><MergeIcon :size="22" /></span>
            <strong>{{ mergeArmedTargetId === asset.id ? '释放鼠标，立即合并' : '停留 2 秒准备合并' }}</strong>
            <small>{{ mergeArmedTargetId === asset.id ? '保留较新资料，并继承双方图片' : '继续停留即可进入合并状态' }}</small>
            <i />
          </div>
        </article>
      </div>
    </section>

    <Transition name="merge-ready">
      <aside v-if="mergeArmedTargetId && draggingAsset && mergeTargetAsset" class="asset-merge-ready" role="status" aria-live="assertive">
        <span><MergeIcon :size="20" /></span>
        <div>
          <strong>释放后合并至「{{ mergeTargetAsset.canonical_name }}」</strong>
          <p>资料采用「{{ mergeDataAsset?.canonical_name }}」的较新版本<span v-if="mergeImageCount">，保留双方 {{ mergeImageCount }} 张图片</span></p>
        </div>
      </aside>
    </Transition>

    <AppButton class="manual-next-step" type="button" variant="dark" size="lg" @click="goToStoryboard">
      <Clapperboard :size="17" />已确认，进入下一步
    </AppButton>

    <AssetCreateDialog
      :open="showAssetDialog"
      :kind="activeTab"
      :novel-id="projectId"
      :asset="editingAsset"
      :chapter-number="selectedChapter?.number"
      :episode-numbers="chapters.map(item => item.number)"
      :initial-mode="assetDrawerMode"
      @close="closeAssetDialog"
      @created="addCreatedAsset"
      @saved="saveEditedAsset"
    />

    <AssetBatchGenerateDialog
      :open="showBatchDialog"
      :assets="assets"
      :generating-ids="generatingAssetIds"
      :failed-ids="failedAssetIds"
      :submitting="batchGenerating"
      @close="showBatchDialog = false"
      @generate="batchGenerateAssets"
    />
    </ShortDramaWorkspaceShell>
  </main>
</template>

<style scoped>
.manual-page { min-height: 100%; color: #303442; background: #f8f9fc; }
.project-name-line { display: flex; align-items: center; gap: 5px; min-height: 25px; }
.project-name-line strong { max-width: 360px; overflow: hidden; font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.project-name-line button { display: grid; place-items: center; color: #8a91a1; background: transparent; }
.project-name-line input { width: min(320px,45vw); height: 30px; padding: 0 9px; border: 1px solid #6b6df6; border-radius: 7px; outline: none; font: inherit; }
.manual-workspace { padding: 28px 44px 120px; }
.asset-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 24px; min-height: 50px; }
.asset-toolbar nav { display: flex; align-items: center; gap: 26px; }
.asset-toolbar nav button { position: relative; display: flex; align-items: center; gap: 7px; height: 42px; color: #6f7686; background: transparent; font-size: 15px; font-weight: 700; }
.asset-toolbar nav button::after { position: absolute; right: 0; bottom: 0; left: 0; height: 2px; border-radius: 2px; background: #6668f6; content: ''; opacity: 0; transform: scaleX(.6); transition: .18s ease; }
.asset-toolbar nav button.is-active { color: #5d5ff5; }
.asset-toolbar nav button.is-active::after { opacity: 1; transform: scaleX(1); }
.asset-summary { display: flex; align-items: center; gap: 14px; color: #858c9b; font-size: 12px; }
.asset-summary span { display: flex; align-items: center; gap: 4px; white-space: nowrap; }
.asset-summary .chapter-context { color: #5d5ff5; font-weight: 700; }
.asset-scope-switch { display: inline-flex; align-items: center; gap: 2px; padding: 2px; border: 1px solid #e1e3ec; border-radius: 10px; background: #f4f5f9; }
.asset-scope-switch button { min-height: 27px; padding: 0 9px; color: #7d8493; border-radius: 7px; }
.asset-scope-switch button.is-active { color: #5658ec; background: #fff; box-shadow: 0 2px 7px rgb(45 49 72 / 8%); }
.asset-summary > i { width: 1px; height: 13px; background: #dfe1e8; }
.asset-summary strong { color: #303442; }
.generating-summary-dot { width: 6px; height: 6px; border-radius: 999px; background: #686af5; box-shadow: 0 0 0 0 rgb(104 106 245 / 32%); animation: generation-pulse 1.6s ease-out infinite; }
.extraction-task-status { display: grid; grid-template-columns: 38px minmax(0, 1fr); align-items: center; gap: 12px; margin-top: 14px; padding: 13px 15px; border: 1px solid #dfe2eb; border-radius: 12px; color: #626979; background: #fff; }
.extraction-task-status > span { display: grid; width: 38px; height: 38px; place-items: center; border-radius: 10px; color: #6668f6; background: #eff0ff; }
.extraction-task-status > div { display: grid; min-width: 0; gap: 3px; }
.extraction-task-status strong { color: #343947; font-size: 12px; }
.extraction-task-status p { margin: 0; font-size: 11px; line-height: 1.5; }
.extraction-task-status small { overflow: hidden; color: #969dac; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.extraction-task-status.is-running { border-color: #cfd0fb; background: #f7f7ff; }
.extraction-task-status.is-running svg { animation: spin .8s linear infinite; }
.extraction-task-status.is-error { border-color: #f1cfd3; background: #fff7f8; }
.extraction-task-status.is-error > span { color: #bd5f6b; background: #fdebed; }
.icon-button,.text-action { display: inline-flex; align-items: center; gap: 6px; color: #424857; background: transparent; }
.icon-button { padding: 6px; border-radius: 7px; }
.icon-button:hover,.text-action:hover { color: #5d5ff5; background: #f1f1ff; }
.text-action { padding: 7px 9px; border-radius: 8px; font-size: 12px; }
.workspace-state { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: calc(100vh - 240px); color: #9aa1b1; }
.workspace-state span:not(.empty-icon) { margin-top: 12px; font-size: 13px; }
.empty-state .empty-icon { display: grid; place-items: center; width: 64px; height: 64px; color: #b7bcc8; border: 1px solid #e4e6ed; border-radius: 20px; background: #fff; box-shadow: 0 10px 26px rgba(49,54,76,.06); }
.empty-state strong { margin-top: 14px; color: #686f7f; font-size: 14px; }
.empty-state p { margin: 6px 0 18px; font-size: 12px; }
.empty-state > button { display: inline-flex; align-items: center; gap: 6px; height: 34px; padding: 0 14px; color: #fff; border-radius: 9px; background: #5e60f5; font-size: 12px; box-shadow: 0 8px 18px rgba(94,96,245,.2); }
.asset-grid { display: grid; grid-template-columns: repeat(auto-fill,minmax(240px,1fr)); gap: 16px; padding-top: 24px; }
.asset-card { position: relative; overflow: hidden; border: 1px solid var(--app-border); border-radius: 16px; outline: 0; background: var(--app-surface-muted); cursor: grab; transition: transform .22s cubic-bezier(.2,.72,.2,1),box-shadow .22s ease,border-color .22s ease,opacity .18s ease; }
.asset-card:active { cursor: grabbing; }
.asset-card:hover,.asset-card:focus-within { border-color: var(--app-border-strong); box-shadow: var(--app-shadow); transform: translateY(-3px); }
.asset-card.is-drag-source { opacity: .38; transform: scale(.985); }
.asset-card.is-merge-target { border-color: var(--app-accent); box-shadow: 0 0 0 3px var(--app-accent-soft),var(--app-shadow); transform: translateY(-2px); }
.asset-card.is-merging { pointer-events: none; opacity: .62; }
.asset-card-open { display: block; width: 100%; padding: 0; border: 0; outline: 0; color: inherit; background: transparent; text-align: left; cursor: pointer; }
.asset-card-open:focus-visible { box-shadow: inset 0 0 0 3px color-mix(in srgb,var(--app-accent) 38%,transparent); }
.asset-visual { position: relative; display: grid; width: 100%; aspect-ratio: 4/3; place-items: center; overflow: hidden; color: var(--app-text-secondary); background: var(--app-surface-muted); }
.asset-visual.is-generating { color: var(--app-accent); background: color-mix(in srgb,var(--app-accent-soft) 55%,var(--app-surface-muted)); }
.asset-visual.is-generating::before { position: absolute; inset: 0; background: linear-gradient(105deg,transparent 28%,color-mix(in srgb,var(--app-surface-raised) 74%,transparent) 48%,transparent 68%); content: ''; transform: translateX(-100%); animation: generation-shimmer 1.8s ease-in-out infinite; }
.asset-visual img { width: 100%; height: 100%; object-fit: cover; }
.asset-visual::after { position: absolute; inset: 0; pointer-events: none; background: linear-gradient(180deg,transparent 48%,rgb(24 27 34 / 18%) 64%,rgb(20 22 28 / 94%) 100%); content: ''; opacity: 0; transition: opacity .24s ease; }
.asset-visual.is-empty::after { background: linear-gradient(180deg,transparent 42%,color-mix(in srgb,var(--app-surface) 76%,transparent) 66%,var(--app-surface) 100%); opacity: 1; }
.asset-generating-placeholder { position: relative; z-index: 1; display: grid; place-items: center; gap: 7px; text-align: center; }
.asset-generating-placeholder > span { display: grid; width: 46px; height: 46px; place-items: center; border: 1px solid var(--app-border); border-radius: 15px; background: var(--app-surface-raised); box-shadow: var(--app-shadow); }
.asset-generating-placeholder svg { animation: spin 1s linear infinite; }
.asset-generating-placeholder strong { color: var(--app-accent); font-size: 12px; }
.asset-generating-placeholder small { color: var(--app-text-secondary); font-size: 10px; }
.asset-state-badge { position: absolute; top: 10px; left: 10px; z-index: 2; box-shadow: 0 5px 14px rgba(43,46,80,.08); }
.asset-state-badge.is-running svg { animation: spin .8s linear infinite; }
.asset-card-info { position: absolute; right: 0; bottom: 0; left: 0; z-index: 2; display: grid; gap: 5px; padding: 36px 14px 13px; color: #f7f8fb; opacity: 0; transform: translateY(12px); transition: opacity .22s ease,transform .26s cubic-bezier(.2,.72,.2,1); text-shadow: 0 1px 2px rgb(0 0 0 / 48%); }
.asset-card-info strong { overflow: hidden; color: #f7f8fb; font-size: 13px; font-weight: 750; text-overflow: ellipsis; white-space: nowrap; }
.asset-card-info p { min-height: 30px; margin: 0; color: #e1e4eb; font-size: 10px; font-weight: 500; line-height: 1.5; }
.asset-visual.is-empty .asset-card-info { color: var(--app-text); opacity: 1; text-shadow: none; transform: translateY(0); }
.asset-visual.is-empty .asset-card-info :is(strong,p) { color: var(--app-text); }
.asset-visual.is-empty .asset-card-info p { color: var(--app-text-secondary); }
.asset-card-actions { position: absolute; top: 10px; right: 10px; z-index: 4; display: flex; flex-direction: row-reverse; gap: 5px; opacity: 0; pointer-events: none; transform: translateX(12px); transition: opacity .18s ease,transform .24s cubic-bezier(.2,.72,.2,1); }
.asset-card .asset-card-actions :deep(.asset-card-action.app-button--ghost) { position: relative; width: 30px; height: 30px; color: var(--app-text); border: 1px solid var(--app-border-strong); border-radius: 9px; background: var(--app-surface-raised); box-shadow: 0 6px 16px rgb(36 39 54 / 18%); backdrop-filter: blur(9px); transform: translateX(7px); transition: color .16s ease,background .16s ease,transform .22s cubic-bezier(.2,.72,.2,1); }
.asset-card .asset-card-actions :deep(.asset-card-action.app-button--ghost:hover),.asset-card .asset-card-actions :deep(.asset-card-action.app-button--ghost:focus-visible) { color: var(--app-accent); background: var(--app-surface); }
.asset-card .asset-card-actions :deep(.asset-card-action.is-danger:hover),.asset-card .asset-card-actions :deep(.asset-card-action.is-danger:focus-visible) { color: #d65d6d; }
.asset-card-action::after { position: absolute; top: 38px; left: 50%; width: max-content; max-width: 120px; padding: 5px 7px; border-radius: 6px; color: #fff; background: rgb(42 45 54 / 92%); content: attr(data-tooltip); font-size: 9px; line-height: 1; opacity: 0; pointer-events: none; transform: translate(-50%,-4px); transition: opacity .14s ease,transform .14s ease; white-space: nowrap; }
.asset-card-action:hover::after,.asset-card-action:focus-visible::after { opacity: 1; transform: translate(-50%,0); }
.asset-card-action:nth-child(2) { transition-delay: .025s; }
.asset-card-action:nth-child(3) { transition-delay: .05s; }
.asset-card-action:nth-child(4) { transition-delay: .075s; }
.asset-card:hover .asset-visual::after,.asset-card:focus-within .asset-visual::after,.asset-card:hover .asset-card-info,.asset-card:focus-within .asset-card-info { opacity: 1; }
.asset-card:hover .asset-card-info,.asset-card:focus-within .asset-card-info,.asset-card:hover .asset-card-actions,.asset-card:focus-within .asset-card-actions { transform: translate(0); }
.asset-card:hover .asset-card-actions,.asset-card:focus-within .asset-card-actions { opacity: 1; pointer-events: auto; }
.asset-card:hover .asset-card-action,.asset-card:focus-within .asset-card-action { transform: translateX(0); }
.asset-merge-overlay { position: absolute; inset: 0; z-index: 5; display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 7px; padding: 18px; color: var(--app-text); background: var(--app-surface-raised); text-align: center; }
.asset-merge-overlay > span { display: grid; width: 44px; height: 44px; place-items: center; color: var(--app-accent); border: 1px solid var(--app-border-strong); border-radius: 14px; background: var(--app-accent-soft); }
.asset-merge-overlay strong { font-size: 13px; }
.asset-merge-overlay small { color: var(--app-text-muted); font-size: 10px; }
.asset-merge-overlay > i { position: absolute; right: 0; bottom: 0; left: 0; height: 3px; background: var(--app-accent); transform-origin: left; animation: merge-hold-progress 2s linear both; }
.asset-card.is-merge-armed .asset-merge-overlay { color: var(--app-accent); background: var(--app-accent-soft); }
.asset-card.is-merge-armed .asset-merge-overlay > i { animation: none; transform: scaleX(1); }
.asset-merge-ready { position: fixed; top: 88px; right: 24px; z-index: 42; display: grid; grid-template-columns: 40px minmax(0,1fr); align-items: center; gap: 11px; width: min(380px,calc(100vw - 32px)); padding: 12px 14px; color: var(--app-text); border: 1px solid var(--app-border-strong); border-radius: 13px; background: var(--app-surface-raised); box-shadow: var(--app-shadow); }
.asset-merge-ready > span { display: grid; width: 40px; height: 40px; place-items: center; color: var(--app-accent); border-radius: 11px; background: var(--app-accent-soft); }
.asset-merge-ready strong { font-size: 12px; }
.asset-merge-ready p { margin: 3px 0 0; color: var(--app-text-muted); font-size: 10px; line-height: 1.45; }
.merge-ready-enter-active,.merge-ready-leave-active { transition: opacity .16s ease,transform .16s ease; }
.merge-ready-enter-from,.merge-ready-leave-to { opacity: 0; transform: translateY(-7px); }
.manual-next-step { position: fixed; bottom: 22px; left: 50%; z-index: 18; display: flex; align-items: center; gap: 8px; height: 44px; padding: 0 22px; color: #fff; border-radius: 15px; background: #23252c; box-shadow: 0 10px 28px rgba(21,23,31,.2); transform: translateX(-50%); }
.is-spinning { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes generation-shimmer { 55%,100% { transform: translateX(100%); } }
@keyframes generation-pulse { 70%,100% { box-shadow: 0 0 0 7px rgb(104 106 245 / 0%); } }
@keyframes merge-hold-progress { from { transform: scaleX(0); } to { transform: scaleX(1); } }
.manual-dialog-backdrop { position: fixed; inset: 0; z-index: 100; display: grid; place-items: center; padding: 20px; background: rgba(28,31,43,.32); backdrop-filter: blur(4px); }
.manual-dialog { width: min(460px,100%); padding: 22px; border: 1px solid #e1e3eb; border-radius: 18px; background: #fff; box-shadow: 0 24px 70px rgba(28,31,43,.22); }
.manual-dialog header { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 20px; }
.manual-dialog header span { color: #6a6cf4; font-size: 9px; font-weight: 800; letter-spacing: .16em; }
.manual-dialog h2 { margin: 3px 0 0; font-size: 21px; }
.manual-dialog header button { display: grid; place-items: center; width: 34px; height: 34px; }
.manual-dialog label { display: grid; gap: 7px; margin-top: 14px; color: #555c6b; font-size: 12px; font-weight: 700; }
.manual-dialog input,.manual-dialog textarea { width: 100%; padding: 10px 11px; color: #303442; border: 1px solid #dfe2eb; border-radius: 9px; background: #fff; outline: none; font: inherit; font-weight: 400; resize: vertical; }
.manual-dialog input:focus,.manual-dialog textarea:focus { border-color: #7779f8; box-shadow: 0 0 0 3px rgba(94,96,245,.1); }
.manual-dialog footer { display: flex; justify-content: flex-end; gap: 9px; margin-top: 20px; }
.manual-dialog footer button { display: inline-flex; align-items: center; gap: 6px; }
@media (max-width: 900px) {
  .manual-workspace { padding: 16px 16px 100px; }
  .asset-toolbar { align-items: flex-start; flex-direction: column; gap: 8px; }
  .asset-summary { width: 100%; overflow-x: auto; padding-bottom: 4px; }
  .asset-grid { grid-template-columns: 1fr; }
  .asset-merge-ready { top: auto; right: 16px; bottom: 78px; }
}
@media (prefers-reduced-motion: reduce) {
  .asset-visual.is-generating::before,.asset-generating-placeholder svg,.generating-summary-dot { animation: none; }
  .asset-visual.is-generating::before { opacity: .3; transform: none; }
  .asset-merge-overlay > i { animation-timing-function: steps(4,end); }
  .asset-card,.asset-card-info,.asset-card-actions,.asset-card-action,.asset-card-action::after,.asset-visual::after { transition-duration: .01ms; }
}
</style>
