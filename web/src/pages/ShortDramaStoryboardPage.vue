<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Boxes,
  Clapperboard,
  Copy,
  GripVertical,
  ImageIcon,
  LoaderCircle,
  MonitorPlay,
  PanelsTopLeft,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
  Upload,
  UsersRound,
  Volume2,
  Workflow,
} from 'lucide-vue-next'
import AppSelect from '@/components/AppSelect.vue'
import AssetCreateDialog from '@/components/AssetCreateDialog.vue'
import BillingPriceTag from '@/components/BillingPriceTag.vue'
import ChapterDetailDrawer from '@/components/ChapterDetailDrawer.vue'
import SceneAssetActionMenu from '@/components/SceneAssetActionMenu.vue'
import SceneAssetVariantPicker, { type SceneAssetVariantSelection } from '@/components/SceneAssetVariantPicker.vue'
import ScenePromptEditor, { type ScenePromptMentionOption } from '@/components/ScenePromptEditor.vue'
import SceneReferenceMediaBar from '@/components/SceneReferenceMediaBar.vue'
import SceneVideoParameterPicker from '@/components/SceneVideoParameterPicker.vue'
import ShortDramaBatchVideoDialog, { type BatchVideoSceneOption } from '@/components/ShortDramaBatchVideoDialog.vue'
import ShortDramaSceneStatusRail from '@/components/ShortDramaSceneStatusRail.vue'
import ShortDramaWorkspaceShell from '@/components/ShortDramaWorkspaceShell.vue'
import SceneVideoGenerationHistory from '@/components/SceneVideoGenerationHistory.vue'
import VideoGenerationErrorState from '@/components/VideoGenerationErrorState.vue'
import CreativeCanvas from '@/features/workbench/pages/CreativeCanvas.vue'
import WorkbenchCanvasIdentity from '@/features/workbench/components/WorkbenchCanvasIdentity.vue'
import { api, mediaUrl, sleep } from '@/api'
import { appConfirm } from '@/shared/confirmDialog'
import { notice } from '@/shared/notice'
import { estimateVideoCost } from '@/shared/modelPricing'
import { episodeDisplayLabel, stripChapterOrdinal } from '@/shared/chapterTitle'
import { chapterHasCompletedVideo } from '@/shared/chapterVideoTimeline'
import { resolveSceneGenerationState, type SceneStatusRailItem } from '@/shared/sceneGenerationStatus'
import { replaceSceneAssetSelection } from '@/shared/sceneAssetSelection'
import { buildVideoInputImageReferences, referencedVideoMedia, videoReferenceMentionSyntax } from '@/shared/scenePromptReferences'
import { readShortDramaSettings } from '@/shared/shortDramaProject'
import { analysisGate } from '@/shared/analysisGate'
import { nextManualSceneSequence } from '@/shared/manualSceneSequence'
import { formatVideoGenerationError } from '@/shared/videoGenerationError'
import { AssetTypeEnum, TaskStatusEnum } from '@/types'
import type { Asset, Chapter, Novel, Scene, Video as VideoResult, VideoGenerationModel, VideoInputImageReference, VideoReferenceMedia } from '@/types'

interface ProjectView extends Novel {
  aspectRatio: string
  resolution: string
  style: string
  creationMode: 'agent' | 'manual'
}

interface SceneDraft {
  description: string
  prompt: string
  duration: number
  selectedAssetIds: number[]
  selectedVariantIds: Record<number, number | null>
  videoGenerationMode: 'reference' | 'keyframes'
  firstFrameUrl: string
  lastFrameUrl: string
  referenceMedia: VideoReferenceMedia[]
  videoResolution: string
  videoAspectRatio: string
  returnLastFrame: boolean
}

const terminalTaskStatuses = new Set([
  TaskStatusEnum.COMPLETED,
  TaskStatusEnum.FAILED,
  TaskStatusEnum.CANCELLED,
])

const route = useRoute()
const router = useRouter()
const projectId = computed(() => Number(route.params.projectId))
const project = ref<ProjectView | null>(null)
const chapters = ref<Chapter[]>([])
const activeChapterId = ref(0)
const activeChapter = ref<Chapter | null>(null)
const assets = ref<Asset[]>([])
const scenes = ref<Scene[]>([])
const activeSceneId = ref(0)
const chapterToolbarHeight = ref(104)
const videoModels = ref<VideoGenerationModel[]>([])
const selectedVideoModel = ref('')
const videos = ref<Record<number, VideoResult[]>>({})
const videoPageEnabled = computed(() => chapterHasCompletedVideo(scenes.value, videos.value))
const loading = ref(true)
const generatingChapterIds = ref<Set<number>>(new Set())
const generatingVideoSceneIds = ref<Set<number>>(new Set())
const refreshingVideoHistorySceneIds = ref<Set<number>>(new Set())
const generationErrors = ref<Record<number, string>>({})
const videoGenerationErrors = ref<Record<number, string>>({})
const sceneDrafts = ref<Record<number, SceneDraft>>({})
const highlightedReferenceKey = ref('')
const openAssetPickerKey = ref('')
const assetPickerFocusIds = ref<Record<string, number>>({})
const assetPickerReplaceAssetIds = ref<Record<string, number>>({})
const openAssetActionKey = ref('')
const editingAsset = ref<Asset | null>(null)
const uploadingFrameKey = ref('')
const uploadingReferenceSceneIds = ref<Set<number>>(new Set())
const savingCanvasIdentity = ref(false)
const chapterDetailOpen = ref(false)
const savingChapterDetails = ref(false)
const batchGeneratingVideos = ref(false)
const batchVideoDialogOpen = ref(false)
let alive = true
let chapterLoadVersion = 0
let chapterToolbarObserver: ResizeObserver | undefined
let sceneScrollContainer: HTMLElement | null = null
let sceneScrollFrame = 0
let sceneScrollUnlockTimer: ReturnType<typeof setTimeout> | undefined
let programmaticSceneId = 0
const sceneAutoSaveTimers = new Map<number, ReturnType<typeof setTimeout>>()
const sceneSaveQueues = new Map<number, Promise<void>>()

const isAgent = computed(() => project.value?.creationMode === 'agent')
const workspaceView = computed<'workflow' | 'storyboard'>(() => route.query.view === 'workflow' ? 'workflow' : 'storyboard')
const generatingStoryboard = computed(() => generatingChapterIds.value.has(activeChapterId.value))
const waitingAnalysis = ref(false)
const creatingManualScene = ref(false)

async function waitForAnalysisThenGenerate(chapterId: number) {
  const loadVersion = chapterLoadVersion
  waitingAnalysis.value = true
  try {
    // 分析未完成时等待其结束；失败/取消则报错引导回剧本页
    for (;;) {
      if (!alive || chapterLoadVersion !== loadVersion) return
      const task = (await api.novelAnalysis(projectId.value)).data
      const gate = analysisGate(task?.status)
      if (gate === 'generate') break
      if (gate === 'failed') {
        throw new Error(task?.error_message || '项目分析失败，请回到剧本页重新分析')
      }
      await sleep(3000)
    }
    if (!alive || chapterLoadVersion !== loadVersion) return
    waitingAnalysis.value = false
    await generateChapterStoryboard(chapterId)
  } catch (error) {
    if (chapterLoadVersion === loadVersion) {
      const message = (error as Error).message
      setGenerationError(chapterId, message)
      notice.error(message)
    }
  } finally {
    if (chapterLoadVersion === loadVersion) waitingAnalysis.value = false
  }
}
const generationError = computed(() => generationErrors.value[activeChapterId.value] || '')
const videoModelOptions = computed(() => videoModels.value.map(item => ({ value: String(item.config_id), label: item.name })))
const videoModelSelectWidth = computed(() => Math.min(420, Math.max(
  220,
  ...videoModelOptions.value.map(option => Math.ceil(Array.from(option.label).reduce(
    (width, character) => width + (/^[\x00-\x7F]$/.test(character) ? 7.2 : 13),
    42,
  ))),
)))
const selectedVideoModelConfig = computed(() => videoModels.value.find(item => String(item.config_id) === selectedVideoModel.value) || null)
const sceneStatusItems = computed<SceneStatusRailItem[]>(() => scenes.value.map(scene => ({
  sceneId: scene.id,
  sequence: scene.sequence,
  state: resolveSceneGenerationState(selectedVideoFor(scene), Boolean(sceneVideoError(scene))),
})))
const batchVideoSceneOptions = computed<BatchVideoSceneOption[]>(() => scenes.value.map(scene => {
  const disabledReason = batchVideoDisabledReason(scene)
  return {
    id: scene.id,
    sequence: scene.sequence,
    disabled: Boolean(disabledReason),
    disabledReason,
  }
}))
const batchVideoCostByScene = computed<Record<number, number>>(() => Object.fromEntries(
  scenes.value.map(scene => [scene.id, sceneVideoEstimate(scene)]),
))
const assetGroups = computed(() => [
  { type: AssetTypeEnum.PERSON, label: '出镜角色', icon: UsersRound, items: assets.value.filter(item => item.asset_type === AssetTypeEnum.PERSON) },
  { type: AssetTypeEnum.SCENE, label: '分镜场景', icon: ImageIcon, items: assets.value.filter(item => item.asset_type === AssetTypeEnum.SCENE) },
  { type: AssetTypeEnum.ITEM, label: '场景道具', icon: Boxes, items: assets.value.filter(item => item.asset_type === AssetTypeEnum.ITEM) },
])

function makeSceneDraft(scene: Scene): SceneDraft {
  const metadata = scene?.metadata && typeof scene.metadata === 'object' ? scene.metadata : {}
  // 资产引用统一以持久化的 scene.assets / asset_ids 为准，与画布工作流共用同一份数据。
  const linkedAssetIds = scene.assets?.map(item => item.id) ?? scene.asset_ids ?? []
  return {
    description: scene.description || '',
    prompt: scene.prompt || '',
    duration: scene.duration || 6,
    selectedAssetIds: [...new Set(linkedAssetIds)],
    selectedVariantIds: readSelectedVariantIds(metadata.asset_variant_ids),
    videoGenerationMode: metadata.video_generation_mode === 'keyframes' ? 'keyframes' : 'reference',
    firstFrameUrl: typeof metadata.first_frame_url === 'string' ? metadata.first_frame_url : '',
    lastFrameUrl: typeof metadata.last_frame_url === 'string' ? metadata.last_frame_url : '',
    referenceMedia: readReferenceMedia(metadata.video_reference_media),
    videoResolution: typeof metadata.video_resolution === 'string' ? metadata.video_resolution : '',
    videoAspectRatio: typeof metadata.video_aspect_ratio === 'string' ? metadata.video_aspect_ratio : '',
    returnLastFrame: metadata.return_last_frame === true,
  }
}

function readReferenceMedia(value: unknown): VideoReferenceMedia[] {
  if (!Array.isArray(value)) return []
  return value.flatMap(item => {
    if (!item || typeof item !== 'object') return []
    const media = item as Record<string, unknown>
    if ((media.type !== 'image' && media.type !== 'video') || typeof media.url !== 'string' || !media.url) return []
    return [{
      type: media.type,
      url: media.url,
      name: typeof media.name === 'string' ? media.name : undefined,
      content_type: typeof media.content_type === 'string' ? media.content_type : undefined,
      size_bytes: typeof media.size_bytes === 'number' ? media.size_bytes : undefined,
      width: typeof media.width === 'number' ? media.width : undefined,
      height: typeof media.height === 'number' ? media.height : undefined,
      duration: typeof media.duration === 'number' ? media.duration : undefined,
      fps: typeof media.fps === 'number' ? media.fps : undefined,
      codec: typeof media.codec === 'string' ? media.codec : undefined,
    } satisfies VideoReferenceMedia]
  })
}

function readSelectedVariantIds(value: unknown): Record<number, number | null> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  const selections: Record<number, number | null> = {}
  for (const [assetIdValue, variantIdValue] of Object.entries(value)) {
    const assetId = Number(assetIdValue)
    if (!Number.isInteger(assetId) || assetId < 1) continue
    if (variantIdValue === null) selections[assetId] = null
    else {
      const variantId = Number(variantIdValue)
      if (Number.isInteger(variantId) && variantId > 0) selections[assetId] = variantId
    }
  }
  return selections
}

function draftFor(scene: Scene) {
  if (!sceneDrafts.value[scene.id]) sceneDrafts.value[scene.id] = makeSceneDraft(scene)
  return sceneDrafts.value[scene.id]
}

function initializeSceneDrafts(items: Scene[]) {
  sceneDrafts.value = Object.fromEntries(items.map(scene => [scene.id, makeSceneDraft(scene)]))
}

function setSceneBusy(target: typeof generatingVideoSceneIds, sceneId: number, value: boolean) {
  const next = new Set(target.value)
  value ? next.add(sceneId) : next.delete(sceneId)
  target.value = next
}

function currentVideoId(scene: Scene) {
  const records = videos.value[scene.id] || []
  const configuredId = Number(scene.metadata?.current_video_id)
  if (Number.isInteger(configuredId) && records.some(record => record.id === configuredId)) return configuredId
  return records[0]?.id
}

function selectedVideoFor(scene: Scene) {
  const records = videos.value[scene.id] || []
  const selectedId = currentVideoId(scene)
  return records.find(record => record.id === selectedId) || records[0]
}

function setSceneVideoError(sceneId: number, message = '') {
  const next = { ...videoGenerationErrors.value }
  if (message) next[sceneId] = message
  else delete next[sceneId]
  videoGenerationErrors.value = next
}

function sceneVideoError(scene: Scene) {
  const localError = videoGenerationErrors.value[scene.id]
  if (localError) return localError
  const video = selectedVideoFor(scene)
  if (!video || (video.status !== TaskStatusEnum.FAILED && video.status !== TaskStatusEnum.CANCELLED)) return ''
  const metadata = video.metadata || {}
  for (const key of ['error_message', 'error', 'message', 'detail']) {
    const value = metadata[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return video.status === TaskStatusEnum.CANCELLED ? '视频生成任务已取消' : '视频生成失败，请检查生成参数后重试'
}

function canGenerateSceneVideo(scene: Scene) {
  const draft = draftFor(scene)
  const model = selectedVideoModelConfig.value
  return Boolean(model
    && model.capabilities.generation_modes.includes(draft.videoGenerationMode)
    && !referenceLimitError(scene, model)
    && draft.prompt.trim()
    && (draft.videoGenerationMode === 'reference' || (draft.firstFrameUrl && draft.lastFrameUrl)))
}

function modelResolution(model: VideoGenerationModel | null) {
  if (!model) return project.value?.resolution || '720p'
  const projectResolution = project.value?.resolution || ''
  return model.capabilities.resolutions.includes(projectResolution)
    ? projectResolution
    : model.capabilities.default_resolution
}

function modelAspectRatio(model: VideoGenerationModel, mode: SceneDraft['videoGenerationMode']) {
  const supported = model.capabilities.aspect_ratios_by_mode[mode] || model.capabilities.aspect_ratios
  const projectRatio = project.value?.aspectRatio || ''
  if (supported.includes(projectRatio)) return projectRatio
  if (supported.includes(model.capabilities.default_aspect_ratio)) return model.capabilities.default_aspect_ratio
  return supported[0] || 'adaptive'
}

function sceneResolution(scene: Scene, model: VideoGenerationModel | null = selectedVideoModelConfig.value) {
  const saved = draftFor(scene).videoResolution
  if (model?.capabilities.resolutions.includes(saved)) return saved
  return modelResolution(model)
}

function sceneAspectRatio(scene: Scene, model: VideoGenerationModel | null = selectedVideoModelConfig.value) {
  if (!model) return draftFor(scene).videoAspectRatio || project.value?.aspectRatio || 'adaptive'
  const draft = draftFor(scene)
  const supported = model.capabilities.aspect_ratios_by_mode[draft.videoGenerationMode]
    || model.capabilities.aspect_ratios
  if (supported.includes(draft.videoAspectRatio)) return draft.videoAspectRatio
  return modelAspectRatio(model, draft.videoGenerationMode)
}

function sceneDuration(scene: Scene, model: VideoGenerationModel | null = selectedVideoModelConfig.value) {
  const draftDuration = Math.round(Number(draftFor(scene).duration) || 0)
  if (!model) return Math.max(1, draftDuration)
  return Math.max(
    model.capabilities.duration_min,
    Math.min(model.capabilities.duration_max, draftDuration),
  )
}

function sceneVideoEstimate(scene: Scene) {
  const model = selectedVideoModelConfig.value
  if (!model) return 0
  const draft = draftFor(scene)
  const hasVideoReference = draft.referenceMedia.some(item => item.type === 'video')
  const inputVideoSeconds = draft.referenceMedia.reduce(
    (sum, item) => item.type === 'video' ? sum + (Number(item.duration) || 0) : sum,
    0,
  )
  return estimateVideoCost(
    model.pricing,
    sceneResolution(scene, model),
    sceneDuration(scene, model),
    hasVideoReference,
    inputVideoSeconds,
  )
}

function selectedAssetsFor(scene: Scene, group: (typeof assetGroups.value)[number]) {
  const selectedIds = draftFor(scene).selectedAssetIds
  return group.items.filter(item => selectedIds.includes(item.id))
}

function assetPickerKey(scene: Scene, type: number) {
  return `${scene.id}:${type}`
}

function assetRowPickerAnchorId(scene: Scene, asset: Asset) {
  return `asset-row-picker-trigger-${scene.id}-${asset.id}`
}

function assetPickerAnchorId(scene: Scene, type: number) {
  const key = assetPickerKey(scene, type)
  const replaceAssetId = assetPickerReplaceAssetIds.value[key]
  return replaceAssetId
    ? `asset-row-picker-trigger-${scene.id}-${replaceAssetId}`
    : `asset-picker-trigger-${key}`
}

function assetActionKey(scene: Scene, asset: Asset) {
  return `${scene.id}:${asset.id}`
}

function toggleAssetActionMenu(scene: Scene, asset: Asset) {
  const key = assetActionKey(scene, asset)
  openAssetActionKey.value = openAssetActionKey.value === key ? '' : key
}

function closeAssetActionsFromOutside(event: PointerEvent) {
  if (!openAssetActionKey.value) return
  const target = event.target
  if (!(target instanceof Element) || !target.closest('.scene-asset-actions')) openAssetActionKey.value = ''
}

function closeAssetActionsFromEscape(event: KeyboardEvent) {
  if (event.key === 'Escape') openAssetActionKey.value = ''
}

function editSceneAsset(asset: Asset) {
  openAssetActionKey.value = ''
  editingAsset.value = asset
}

function closeAssetEditor() {
  editingAsset.value = null
}

function saveEditedAsset(asset: Asset) {
  assets.value = assets.value.map(item => item.id === asset.id ? asset : item)
  if (editingAsset.value?.id === asset.id) editingAsset.value = asset
}

async function removeAssetFromScene(scene: Scene, asset: Asset) {
  const confirmed = await appConfirm({
    title: `移除「${asset.canonical_name}」？`,
    message: '只会从当前分镜移除，不会删除项目资产及其衍生状态。',
    confirmLabel: '确认移除',
    tone: 'danger',
  })
  if (!confirmed) return
  updateAssetSelection(scene, { assetId: asset.id, variantId: null, selected: false })
  openAssetActionKey.value = ''
  notice.success(`已从当前分镜移除「${asset.canonical_name}」`)
}

function editingAssetKind(asset: Asset | null): 'character' | 'scene' | 'prop' {
  if (asset?.asset_type === AssetTypeEnum.SCENE) return 'scene'
  if (asset?.asset_type === AssetTypeEnum.ITEM) return 'prop'
  return 'character'
}

function toggleAssetPicker(scene: Scene, type: number) {
  const key = assetPickerKey(scene, type)
  const isSameAddPicker = openAssetPickerKey.value === key && !assetPickerReplaceAssetIds.value[key]
  assetPickerFocusIds.value = { ...assetPickerFocusIds.value, [key]: 0 }
  assetPickerReplaceAssetIds.value = { ...assetPickerReplaceAssetIds.value, [key]: 0 }
  openAssetPickerKey.value = isSameAddPicker ? '' : key
}

function toggleAssetReplacementPicker(scene: Scene, type: number, asset: Asset) {
  const key = assetPickerKey(scene, type)
  const isSameReplacement = openAssetPickerKey.value === key && assetPickerReplaceAssetIds.value[key] === asset.id
  assetPickerFocusIds.value = { ...assetPickerFocusIds.value, [key]: asset.id }
  assetPickerReplaceAssetIds.value = { ...assetPickerReplaceAssetIds.value, [key]: asset.id }
  openAssetPickerKey.value = isSameReplacement ? '' : key
}

function closeAssetPicker(key: string) {
  if (openAssetPickerKey.value === key) openAssetPickerKey.value = ''
}

function updateAssetSelection(scene: Scene, selection: SceneAssetVariantSelection) {
  const draft = draftFor(scene)
  if (selection.selected) {
    if (!draft.selectedAssetIds.includes(selection.assetId)) {
      draft.selectedAssetIds = [...draft.selectedAssetIds, selection.assetId]
    }
    draft.selectedVariantIds = {
      ...draft.selectedVariantIds,
      [selection.assetId]: selection.variantId,
    }
    scheduleSceneSave(scene)
    return
  }
  draft.selectedAssetIds = draft.selectedAssetIds.filter(id => id !== selection.assetId)
  const nextSelections = { ...draft.selectedVariantIds }
  delete nextSelections[selection.assetId]
  draft.selectedVariantIds = nextSelections
  scheduleSceneSave(scene)
}

function replaceAssetSelection(scene: Scene, replaceAssetId: number, selection: SceneAssetVariantSelection) {
  const draft = draftFor(scene)
  const replacement = replaceSceneAssetSelection(draft, replaceAssetId, selection)
  draft.selectedAssetIds = replacement.selectedAssetIds
  draft.selectedVariantIds = replacement.selectedVariantIds
  scheduleSceneSave(scene)
}

function handleAssetPickerSelection(scene: Scene, type: number, selection: SceneAssetVariantSelection) {
  const key = assetPickerKey(scene, type)
  const replaceAssetId = assetPickerReplaceAssetIds.value[key]
  if (!replaceAssetId) {
    updateAssetSelection(scene, selection)
    return
  }
  replaceAssetSelection(scene, replaceAssetId, selection)
  closeAssetPicker(key)
}

function selectedVariantFor(scene: Scene, asset: Asset) {
  const draft = draftFor(scene)
  if (Object.prototype.hasOwnProperty.call(draft.selectedVariantIds, asset.id)) {
    const variantId = draft.selectedVariantIds[asset.id]
    return variantId === null ? null : asset.variants?.find(variant => variant.id === variantId) || null
  }
  const chapterNumber = activeChapter.value?.number
  const matching = (asset.variants || []).filter(variant => chapterNumber && variant.chapter_numbers?.includes(chapterNumber))
  return matching.reduce((latest, variant) => !latest || variant.id > latest.id ? variant : latest, null as NonNullable<Asset['variants']>[number] | null)
}

function resolvedSelectedVariantIdsFor(scene: Scene) {
  const draft = draftFor(scene)
  return Object.fromEntries(draft.selectedAssetIds.flatMap(assetId => {
    const asset = assets.value.find(item => item.id === assetId)
    if (!asset) return []
    return [[assetId, selectedVariantFor(scene, asset)?.id ?? null]]
  })) as Record<number, number | null>
}

function selectedAssetLabel(scene: Scene, asset: Asset) {
  const variant = selectedVariantFor(scene, asset)
  return variant ? `${asset.canonical_name} · ${variant.name}` : asset.canonical_name
}

function selectedAssetImage(scene: Scene, asset: Asset) {
  const variant = selectedVariantFor(scene, asset)
  if (variant) return variant.images[0] || ''
  return asset.main_image || asset.angle_image_1 || asset.angle_image_2 || ''
}

function selectedAssetReferenceImages(scene: Scene, asset: Asset) {
  const variant = selectedVariantFor(scene, asset)
  if (variant) return [...new Set(variant.images.filter(Boolean))]

  const gallery = Array.isArray(asset.metadata?.image_gallery)
    ? asset.metadata.image_gallery.filter(
        (value): value is string => typeof value === 'string' && Boolean(value.trim()),
      )
    : []
  let sources = [asset.main_image, asset.angle_image_1, asset.angle_image_2, ...gallery]
    .filter((value): value is string => Boolean(value))
  const selected = asset.metadata?.selected_image_urls
  if (Array.isArray(selected)) {
    const selectedUrls = new Set(
      selected.filter(
        (value): value is string => typeof value === 'string' && Boolean(value.trim()),
      ),
    )
    sources = sources.filter(source => selectedUrls.has(source))
  } else {
    sources = sources.slice(0, 1)
  }
  return [...new Set(sources)]
}

function videoInputImageReferences(scene: Scene) {
  const draft = draftFor(scene)
  const selectedAssets = assets.value.filter(asset => draft.selectedAssetIds.includes(asset.id))
  return buildVideoInputImageReferences(
    draft.prompt,
    selectedAssets.map(asset => ({
      assetId: asset.id,
      label: selectedAssetLabel(scene, asset),
      mentionNames: [asset.canonical_name, ...(asset.aliases || [])],
      imageUrls: selectedAssetReferenceImages(scene, asset),
    })),
    draft.referenceMedia,
  )
}

function problemImageReference(scene: Scene): VideoInputImageReference | undefined {
  const error = sceneVideoError(scene)
  if (!error) return undefined
  const number = formatVideoGenerationError(error).referenceImageNumber
  return number
    ? videoInputImageReferences(scene).find(reference => reference.number === number)
    : undefined
}

function highlightedMediaIndex(scene: Scene) {
  const prefix = `media:${scene.id}:`
  return highlightedReferenceKey.value.startsWith(prefix)
    ? Number(highlightedReferenceKey.value.slice(prefix.length))
    : undefined
}

async function locateProblemImageReference(scene: Scene, number: number) {
  const reference = videoInputImageReferences(scene).find(item => item.number === number)
  if (!reference) return
  const key = reference.source === 'asset'
    ? `asset:${scene.id}:${reference.assetId}`
    : `media:${scene.id}:${reference.mediaIndex}`
  highlightedReferenceKey.value = key
  await nextTick()
  const sceneElement = document.getElementById(`scene-${scene.id}`)
  const selector = reference.source === 'asset'
    ? `[data-reference-asset-id="${reference.assetId}"]`
    : `[data-reference-media-index="${reference.mediaIndex}"]`
  sceneElement?.querySelector<HTMLElement>(selector)?.scrollIntoView({
    behavior: 'smooth',
    block: 'center',
    inline: 'center',
  })
  window.setTimeout(() => {
    if (highlightedReferenceKey.value === key) highlightedReferenceKey.value = ''
  }, 1800)
}

function selectedAssetReferenceImageCount(scene: Scene) {
  return videoInputImageReferences(scene)
    .filter(reference => reference.source === 'asset').length
}

function promptMentionOptions(scene: Scene): ScenePromptMentionOption[] {
  const assetOptions = assetGroups.value
    .filter(group => [AssetTypeEnum.PERSON, AssetTypeEnum.SCENE, AssetTypeEnum.ITEM].includes(group.type))
    .flatMap(group => selectedAssetsFor(scene, group).map(asset => ({
    id: `asset-${asset.id}`,
    kind: asset.asset_type === AssetTypeEnum.PERSON
      ? 'person' as const
      : asset.asset_type === AssetTypeEnum.SCENE
        ? 'scene' as const
        : 'item' as const,
    label: selectedAssetLabel(scene, asset),
    syntax: `@{${asset.canonical_name}}`,
    group: asset.asset_type === AssetTypeEnum.PERSON ? '角色' : asset.asset_type === AssetTypeEnum.SCENE ? '场景' : '道具',
    previewUrl: selectedAssetImage(scene, asset) || undefined,
    thumbnailUrl: selectedAssetImage(scene, asset) || undefined,
    description: asset.description || asset.canonical_name,
  })))
  const mediaOptions: ScenePromptMentionOption[] = draftFor(scene).referenceMedia.map((reference, index) => ({
    id: `reference-${reference.type}-${reference.url}`,
    kind: reference.type,
    label: reference.name || `${reference.type === 'image' ? '参考图片' : '参考视频'} ${index + 1}`,
    syntax: videoReferenceMentionSyntax(reference),
    group: reference.type === 'image' ? '参考图片' : '参考视频',
    previewUrl: reference.url,
    thumbnailUrl: reference.url,
    description: reference.type === 'image' ? '已上传参考图片' : '已上传参考视频',
  }))
  return [
    ...assetOptions,
    ...mediaOptions,
    {
      id: `duration-${scene.id}`,
      kind: 'duration',
      label: '请设置时长',
      syntax: '@{镜头时长}',
      group: '镜头参数',
      description: '设置 1–30 秒',
    },
  ]
}

function referenceLimitError(scene: Scene, model = selectedVideoModelConfig.value) {
  if (!model || draftFor(scene).videoGenerationMode !== 'reference') return ''
  const draft = draftFor(scene)
  const referencedMedia = referencedVideoMedia(draft.prompt, draft.referenceMedia)
  const imageCount = selectedAssetReferenceImageCount(scene) + referencedMedia.filter(item => item.type === 'image').length
  const videos = referencedMedia.filter(item => item.type === 'video')
  const duration = videos.reduce((total, item) => total + (item.duration || 0), 0)
  if (imageCount > model.capabilities.max_reference_images) return `参考图片超过 ${model.capabilities.max_reference_images} 张（包含资产图）`
  if (videos.length > model.capabilities.max_reference_videos) return `参考视频超过 ${model.capabilities.max_reference_videos} 个`
  if (duration > model.capabilities.reference_video_total_duration_max + 0.001) return `参考视频总时长超过 ${model.capabilities.reference_video_total_duration_max} 秒`
  return ''
}

function fileExtension(file: File) {
  return file.name.split('.').pop()?.toLowerCase() || ''
}

function inspectVideoFile(file: File): Promise<{ duration: number; width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const video = document.createElement('video')
    const url = URL.createObjectURL(file)
    const cleanup = () => URL.revokeObjectURL(url)
    video.preload = 'metadata'
    video.onloadedmetadata = () => {
      const result = { duration: video.duration, width: video.videoWidth, height: video.videoHeight }
      cleanup()
      resolve(result)
    }
    video.onerror = () => {
      cleanup()
      reject(new Error(`无法读取视频“${file.name}”，请确认文件未损坏且编码受支持`))
    }
    video.src = url
  })
}

async function validateReferenceFiles(scene: Scene, files: File[], model: VideoGenerationModel) {
  const capabilities = model.capabilities
  const existingImages = selectedAssetReferenceImageCount(scene) + draftFor(scene).referenceMedia.filter(item => item.type === 'image').length
  const existingVideos = draftFor(scene).referenceMedia.filter(item => item.type === 'video')
  const imageFiles = files.filter(file => capabilities.reference_image_formats.includes(fileExtension(file)))
  const videoFiles = files.filter(file => capabilities.reference_video_formats.includes(fileExtension(file)))
  if (imageFiles.length + videoFiles.length !== files.length) throw new Error('仅支持当前模型配置允许的参考图片及 MP4/MOV 视频')
  if (existingImages + imageFiles.length > capabilities.max_reference_images) {
    throw new Error(`当前模型最多接收 ${capabilities.max_reference_images} 张参考图片，已包含分镜所选资产图`)
  }
  if (existingVideos.length + videoFiles.length > capabilities.max_reference_videos) {
    throw new Error(`当前模型最多接收 ${capabilities.max_reference_videos} 个参考视频`)
  }
  for (const file of imageFiles) {
    if (file.size >= capabilities.reference_image_max_size_mb * 1024 * 1024) throw new Error(`单张参考图片必须小于 ${capabilities.reference_image_max_size_mb}MB`)
  }
  let totalDuration = existingVideos.reduce((total, item) => total + (item.duration || 0), 0)
  for (const file of videoFiles) {
    if (file.size > capabilities.reference_video_max_size_mb * 1024 * 1024) throw new Error(`单个参考视频不能超过 ${capabilities.reference_video_max_size_mb}MB`)
    const metadata = await inspectVideoFile(file)
    if (metadata.duration < capabilities.reference_media_duration_min || metadata.duration > capabilities.reference_video_duration_max) {
      throw new Error(`当前模型要求单个参考视频时长为 ${capabilities.reference_media_duration_min}-${capabilities.reference_video_duration_max} 秒`)
    }
    const ratio = metadata.width / metadata.height
    const pixels = metadata.width * metadata.height
    if (metadata.width < capabilities.reference_media_side_min || metadata.width > capabilities.reference_media_side_max
      || metadata.height < capabilities.reference_media_side_min || metadata.height > capabilities.reference_media_side_max
      || ratio < capabilities.reference_media_ratio_min || ratio > capabilities.reference_media_ratio_max
      || pixels < capabilities.reference_video_pixels_min || pixels > capabilities.reference_video_pixels_max) {
      throw new Error(`视频“${file.name}”的尺寸或宽高比不符合当前模型要求`)
    }
    totalDuration += metadata.duration
  }
  if (totalDuration > capabilities.reference_video_total_duration_max + 0.001) {
    throw new Error(`当前模型参考视频总时长不能超过 ${capabilities.reference_video_total_duration_max} 秒`)
  }
}

async function uploadReferenceMedia(scene: Scene, files: File[]) {
  const model = selectedVideoModelConfig.value
  if (!model || !files.length || uploadingReferenceSceneIds.value.has(scene.id)) return
  setSceneBusy(uploadingReferenceSceneIds, scene.id, true)
  try {
    await validateReferenceFiles(scene, files, model)
    const uploaded: VideoReferenceMedia[] = []
    for (const file of files) uploaded.push(await api.uploadVideoReference(file, model.config_id))
    draftFor(scene).referenceMedia.push(...uploaded)
    await saveScene(scene, false)
    notice.success(`已添加 ${uploaded.length} 个参考素材`)
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    setSceneBusy(uploadingReferenceSceneIds, scene.id, false)
  }
}

async function removeReferenceMedia(scene: Scene, index: number) {
  draftFor(scene).referenceMedia.splice(index, 1)
  await saveScene(scene, false)
}

async function uploadFrame(scene: Scene, kind: 'first' | 'last', event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!file.type.startsWith('image/')) {
    notice.error('首尾帧仅支持图片文件')
    return
  }
  if (file.size > 20 * 1024 * 1024) {
    notice.error('图片大小不能超过 20MB')
    return
  }
  const uploadKey = `${scene.id}:${kind}`
  uploadingFrameKey.value = uploadKey
  try {
    const uploaded = await api.upload(file)
    const url = uploaded.url || mediaUrl(`/media/${uploaded.filename}`)
    const draft = draftFor(scene)
    if (kind === 'first') draft.firstFrameUrl = url
    else draft.lastFrameUrl = url
    await saveScene(scene, false)
    notice.success(kind === 'first' ? '首帧已上传' : '尾帧已上传')
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    if (uploadingFrameKey.value === uploadKey) uploadingFrameKey.value = ''
  }
}

async function setVideoGenerationMode(scene: Scene, mode: 'reference' | 'keyframes') {
  draftFor(scene).videoGenerationMode = mode
  await saveScene(scene, false)
}

function setChapterGenerating(chapterId: number, value: boolean) {
  const next = new Set(generatingChapterIds.value)
  value ? next.add(chapterId) : next.delete(chapterId)
  generatingChapterIds.value = next
}

function setGenerationError(chapterId: number, message = '') {
  generationErrors.value = { ...generationErrors.value, [chapterId]: message }
}

async function fetchChapterScenes(chapterId: number) {
  const response = await api.workbenchBootstrap(projectId.value, chapterId)
  return {
    chapter: response.data.chapter,
    assets: response.data.assets,
    scenes: response.data.scenes,
    videos: response.data.videos as Record<number, VideoResult[]>,
  }
}

function showChapterScenes(result: Awaited<ReturnType<typeof fetchChapterScenes>>) {
  activeChapter.value = result.chapter
  assets.value = result.assets
  scenes.value = result.scenes
  videos.value = result.videos
  videoGenerationErrors.value = {}
  const requestedSceneId = Number(route.query.scene)
  const requestedScene = result.scenes.find(scene => scene.id === requestedSceneId)
  activeSceneId.value = requestedScene?.id || result.scenes[0]?.id || 0
  initializeSceneDrafts(result.scenes)
  void nextTick(() => {
    setupSceneTracking()
    if (requestedScene) selectSceneById(requestedScene.id)
  })
}

async function createManualScene(chapterId = activeChapterId.value) {
  if (creatingManualScene.value) return
  const chapter = chapters.value.find(item => item.id === chapterId)
  if (!chapter) return
  creatingManualScene.value = true
  try {
    const created = (await api.createScene({
      chapter_id: chapterId,
      sequence: nextManualSceneSequence(scenes.value),
      description: stripChapterOrdinal(chapter.name) || '新分镜',
      prompt: '',
      duration: 6,
    })).data
    if (activeChapterId.value !== chapterId) return
    if (!scenes.value.length) {
      scenes.value = [created]
    } else {
      scenes.value = [...scenes.value, created]
    }
    activeSceneId.value = created.id
    videos.value[created.id] = []
    initializeSceneDrafts([created])
    void nextTick(setupSceneTracking)
    // 人工模式创建分镜后切到故事板视图，直接展示空白分镜操作框
    if (workspaceView.value === 'workflow') selectWorkspaceView('storyboard')
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    creatingManualScene.value = false
  }
}

async function generateChapterStoryboard(chapterId: number) {
  if (!chapterId || generatingChapterIds.value.has(chapterId)) return
  setChapterGenerating(chapterId, true)
  setGenerationError(chapterId)
  try {
    const task = (await api.generateScenes(chapterId)).data
    let current = task
    while (alive && !terminalTaskStatuses.has(current.status)) {
      await sleep(2200)
      current = (await api.task(task.id)).data
    }
    if (!alive) return
    if (current.status !== TaskStatusEnum.COMPLETED) throw new Error(current.error_message || 'Agent 分镜生成失败')
    const result = await fetchChapterScenes(chapterId)
    if (activeChapterId.value === chapterId) showChapterScenes(result)
    const chapterNumber = chapters.value.find(item => item.id === chapterId)?.number || ''
    notice.success(`第 ${chapterNumber} 集分镜已生成`)
  } catch (error) {
    const message = (error as Error).message
    setGenerationError(chapterId, message)
    notice.error(message)
  } finally {
    setChapterGenerating(chapterId, false)
  }
}

async function regenerateStoryboard() {
  const chapterId = activeChapterId.value
  if (!chapterId || generatingChapterIds.value.has(chapterId)) return
  // 分析未完成时：等待完成后自动生成本集分镜（不删除现有内容）
  const analysis = (await api.novelAnalysis(projectId.value)).data
  const gate = analysisGate(analysis?.status)
  if (gate === 'failed') {
    notice.error(analysis?.error_message || '项目分析失败，请回到剧本页重新分析')
    return
  }
  if (gate === 'wait') {
    notice.info('项目分析尚未完成，完成后将自动生成本集分镜')
    await waitForAnalysisThenGenerate(chapterId)
    return
  }
  const chapterScenes = [...scenes.value]
  if (!await appConfirm({
    title: '重新生成本集分镜？',
    message: `本集现有 ${chapterScenes.length} 个分镜将被替换，此操作无法撤销。`,
    confirmLabel: '重新生成',
    tone: 'warning',
  })) return
  setChapterGenerating(chapterId, true)
  setGenerationError(chapterId)
  try {
    await Promise.all(chapterScenes.map(scene => api.deleteScene(scene.id)))
    if (activeChapterId.value === chapterId) {
      scenes.value = []
      activeSceneId.value = 0
      sceneDrafts.value = {}
    }
  } catch (error) {
    setChapterGenerating(chapterId, false)
    notice.error((error as Error).message)
    return
  }
  setChapterGenerating(chapterId, false)
  await generateChapterStoryboard(chapterId)
}

async function loadChapter(chapterId: number) {
  const loadVersion = ++chapterLoadVersion
  activeChapterId.value = chapterId
  activeChapter.value = chapters.value.find(item => item.id === chapterId) ?? null
  scenes.value = []
  videos.value = {}
  activeSceneId.value = 0
  sceneDrafts.value = {}
  loading.value = true
  setGenerationError(chapterId)
  try {
    const result = await fetchChapterScenes(chapterId)
    if (loadVersion !== chapterLoadVersion || activeChapterId.value !== chapterId) return
    showChapterScenes(result)
    loading.value = false
    if (!result.scenes.length) {
      if (isAgent.value) await waitForAnalysisThenGenerate(chapterId)
      else await createManualScene(chapterId)
    }
  } catch (error) {
    if (loadVersion !== chapterLoadVersion || activeChapterId.value !== chapterId) return
    const message = (error as Error).message
    setGenerationError(chapterId, message)
    notice.error(message)
  } finally {
    if (loadVersion === chapterLoadVersion && activeChapterId.value === chapterId) loading.value = false
  }
}

async function load() {
  loading.value = true
  try {
    const [novelResponse, chapterResponse, videoModelResponse] = await Promise.all([
      api.novelMeta(projectId.value),
      api.chapters(projectId.value),
      api.videoGenerationModels(),
    ])
    const settings = readShortDramaSettings(novelResponse.data)
    project.value = {
      ...novelResponse.data,
      aspectRatio: settings.aspectRatio || '9:16',
      resolution: settings.resolution || '720p',
      style: settings.style || '写实通用',
      creationMode: novelResponse.data.author?.includes('Agent') ? 'agent' : 'manual',
    }
    chapters.value = chapterResponse.data.items
    videoModels.value = videoModelResponse.data
    if (!videoModels.value.some(item => String(item.config_id) === selectedVideoModel.value)) {
      selectedVideoModel.value = String(videoModels.value[0]?.config_id || '')
    }
    const preferredChapter = Number(route.query.chapter)
    const firstChapter = chapters.value.find(item => item.id === preferredChapter) ?? chapters.value[0]
    if (firstChapter) {
      if (preferredChapter !== firstChapter.id) {
        void router.replace({ query: { ...route.query, chapter: String(firstChapter.id) } })
      }
      await loadChapter(firstChapter.id)
    }
    else loading.value = false
  } catch (error) {
    const message = (error as Error).message
    setGenerationError(activeChapterId.value, message)
    notice.error(message)
    loading.value = false
  }
}

function sceneViewportAnchor() {
  const fixedHeaderHeight = document.querySelector<HTMLElement>('.short-drama-workspace-header')?.getBoundingClientRect().height || 72
  return Math.ceil(fixedHeaderHeight + chapterToolbarHeight.value + 12)
}

function syncActiveSceneFromViewport() {
  if (programmaticSceneId) return
  const elements = [...document.querySelectorAll<HTMLElement>('[data-scene-id]')]
  if (!elements.length) return
  const container = sceneScrollContainer
  if (container && container.scrollTop + container.clientHeight >= container.scrollHeight - 2) {
    activeSceneId.value = Number(elements.at(-1)?.dataset.sceneId) || activeSceneId.value
    return
  }
  const anchor = sceneViewportAnchor()
  let active = elements[0]
  for (const element of elements) {
    if (element.getBoundingClientRect().top > anchor) break
    active = element
  }
  activeSceneId.value = Number(active?.dataset.sceneId) || activeSceneId.value
}

function scheduleProgrammaticSceneUnlock(delay: number) {
  if (sceneScrollUnlockTimer) clearTimeout(sceneScrollUnlockTimer)
  sceneScrollUnlockTimer = setTimeout(() => {
    programmaticSceneId = 0
    syncActiveSceneFromViewport()
  }, delay)
}

function handleSceneScroll() {
  if (programmaticSceneId) {
    scheduleProgrammaticSceneUnlock(180)
    return
  }
  if (sceneScrollFrame) return
  sceneScrollFrame = requestAnimationFrame(() => {
    sceneScrollFrame = 0
    syncActiveSceneFromViewport()
  })
}

function selectScene(scene: Scene) {
  programmaticSceneId = scene.id
  activeSceneId.value = scene.id
  document.getElementById(`scene-${scene.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  scheduleProgrammaticSceneUnlock(700)
}

function selectSceneById(sceneId: number) {
  const scene = scenes.value.find(item => item.id === sceneId)
  if (scene) selectScene(scene)
}

function setupChapterToolbarObserver() {
  chapterToolbarObserver?.disconnect()
  const toolbar = document.querySelector<HTMLElement>('.chapter-toolbar')
  if (!toolbar) return
  const syncHeight = () => {
    chapterToolbarHeight.value = Math.max(1, Math.ceil(toolbar.getBoundingClientRect().height))
  }
  syncHeight()
  if (typeof ResizeObserver !== 'undefined') {
    chapterToolbarObserver = new ResizeObserver(syncHeight)
    chapterToolbarObserver.observe(toolbar)
  }
}

async function selectChapter(chapter: Chapter) {
  if (chapter.id === activeChapterId.value) return
  chapterDetailOpen.value = false
  await flushPendingSceneSaves()
  await router.replace({ query: { ...route.query, chapter: String(chapter.id) } })
  await loadChapter(chapter.id)
}

function setupSceneTracking() {
  setupChapterToolbarObserver()
  const nextContainer = document.querySelector<HTMLElement>('.app-content')
  if (sceneScrollContainer !== nextContainer) {
    sceneScrollContainer?.removeEventListener('scroll', handleSceneScroll)
    sceneScrollContainer = nextContainer
    sceneScrollContainer?.addEventListener('scroll', handleSceneScroll, { passive: true })
  }
  syncActiveSceneFromViewport()
}

function scheduleSceneSave(scene: Scene, delay = 600) {
  const existing = sceneAutoSaveTimers.get(scene.id)
  if (existing) clearTimeout(existing)
  sceneAutoSaveTimers.set(scene.id, setTimeout(() => {
    sceneAutoSaveTimers.delete(scene.id)
    void saveScene(scene)
  }, delay))
}

function updateSceneText(scene: Scene, field: 'description' | 'prompt', event: Event) {
  draftFor(scene)[field] = (event.target as HTMLTextAreaElement).value
  scheduleSceneSave(scene)
}

function updateScenePrompt(scene: Scene, value: string) {
  draftFor(scene).prompt = value
  scheduleSceneSave(scene)
}

function updateSceneDraft<K extends keyof SceneDraft>(scene: Scene, field: K, value: SceneDraft[K]) {
  draftFor(scene)[field] = value
  scheduleSceneSave(scene)
}

async function saveScene(scene: Scene, showNotice = false) {
  const pendingTimer = sceneAutoSaveTimers.get(scene.id)
  if (pendingTimer) clearTimeout(pendingTimer)
  sceneAutoSaveTimers.delete(scene.id)

  const previous = sceneSaveQueues.get(scene.id) ?? Promise.resolve()
  const queued = previous.then(async () => {
    const draft = draftFor(scene)
    const currentScene = scenes.value.find(item => item.id === scene.id) ?? scene
    const duration = sceneDuration(currentScene)
    draft.duration = duration
    try {
      const updated = (await api.updateScene(scene.id, {
        description: draft.description,
        prompt: draft.prompt,
        duration,
        asset_ids: draft.selectedAssetIds,
        metadata: {
          ...(currentScene.metadata || {}),
          video_generation_mode: draft.videoGenerationMode,
          first_frame_url: draft.firstFrameUrl || undefined,
          last_frame_url: draft.lastFrameUrl || undefined,
          asset_variant_ids: draft.selectedVariantIds,
          video_reference_media: draft.referenceMedia,
          video_resolution: sceneResolution(currentScene),
          video_aspect_ratio: sceneAspectRatio(currentScene),
          return_last_frame: draft.returnLastFrame,
        },
      })).data
      scenes.value = scenes.value.map(item => item.id === updated.id ? updated : item)
      if (showNotice) notice.success('分镜已保存')
    } catch (error) {
      notice.error(`自动保存失败：${(error as Error).message}`)
    }
  })
  sceneSaveQueues.set(scene.id, queued)
  await queued
  if (sceneSaveQueues.get(scene.id) === queued) sceneSaveQueues.delete(scene.id)
}

async function flushPendingSceneSaves() {
  const pendingScenes = [...sceneAutoSaveTimers.keys()]
    .map(sceneId => scenes.value.find(scene => scene.id === sceneId))
    .filter((scene): scene is Scene => Boolean(scene))
  for (const timer of sceneAutoSaveTimers.values()) clearTimeout(timer)
  sceneAutoSaveTimers.clear()
  await Promise.all(pendingScenes.map(scene => saveScene(scene)))
  await Promise.all(sceneSaveQueues.values())
}

async function insertSceneAfter(scene: Scene) {
  if (!scene || !activeChapter.value) return
  try {
    const created = (await api.insertSceneAfter(scene.id)).data
    const insertIndex = scenes.value.findIndex(item => item.id === scene.id) + 1
    scenes.value = [
      ...scenes.value.slice(0, insertIndex),
      created,
      ...scenes.value.slice(insertIndex).map(item => ({ ...item, sequence: item.sequence + 1 })),
    ]
    videos.value[created.id] = []
    sceneDrafts.value[created.id] = makeSceneDraft(created)
    await nextTick()
    setupSceneTracking()
    selectScene(created)
    notice.success(`已在分镜 ${scene.sequence} 下方添加新分镜`)
  } catch (error) {
    notice.error((error as Error).message)
  }
}

async function duplicateScene(scene: Scene) {
  if (!scene || !activeChapter.value) return
  const draft = draftFor(scene)
  try {
    const created = (await api.createScene({
      chapter_id: activeChapter.value.id,
      sequence: Math.max(0, ...scenes.value.map(item => item.sequence)) + 1,
      description: draft.description,
      prompt: draft.prompt,
      duration: sceneDuration(scene),
      asset_ids: draft.selectedAssetIds,
      metadata: {
        ...(scene.metadata || {}),
        asset_variant_ids: draft.selectedVariantIds,
        video_generation_mode: draft.videoGenerationMode,
        first_frame_url: draft.firstFrameUrl || undefined,
        last_frame_url: draft.lastFrameUrl || undefined,
        video_reference_media: draft.referenceMedia,
        video_resolution: sceneResolution(scene),
        video_aspect_ratio: sceneAspectRatio(scene),
        return_last_frame: draft.returnLastFrame,
      },
    })).data
    scenes.value.push(created)
    videos.value[created.id] = []
    sceneDrafts.value[created.id] = makeSceneDraft(created)
    await nextTick()
    setupSceneTracking()
    selectScene(created)
    notice.success('分镜已复制')
  } catch (error) {
    notice.error((error as Error).message)
  }
}

async function removeScene(scene: Scene) {
  if (!scene || !await appConfirm({
    title: `删除分镜 ${scene.sequence}？`,
    message: '删除后无法恢复，后续分镜序号不会自动调整。',
    confirmLabel: '删除分镜',
    tone: 'danger',
  })) return
  try {
    await api.deleteScene(scene.id)
    scenes.value = scenes.value.filter(item => item.id !== scene.id)
    delete sceneDrafts.value[scene.id]
    setSceneVideoError(scene.id)
    const next = scenes.value.find(item => item.sequence > scene.sequence) ?? scenes.value.at(-1)
    activeSceneId.value = next?.id || 0
    await nextTick()
    setupSceneTracking()
    if (next) selectScene(next)
    notice.success('分镜已删除')
  } catch (error) {
    notice.error((error as Error).message)
  }
}

async function generateVideo(scene: Scene, showNotice = true): Promise<boolean> {
  const draft = draftFor(scene)
  const selectedModel = selectedVideoModelConfig.value
  if (!selectedModel) {
    if (showNotice) notice.error('请先在设置中启用一个视频模型')
    return false
  }
  if (generatingVideoSceneIds.value.has(scene.id)) return false
  setSceneVideoError(scene.id)
  setSceneBusy(generatingVideoSceneIds, scene.id, true)
  try {
    await saveScene(scene, false)
    let result = (await api.generateVideo(scene.id, Number(selectedVideoModel.value), {
      generation_mode: draft.videoGenerationMode,
      first_frame_url: draft.firstFrameUrl || undefined,
      last_frame_url: draft.lastFrameUrl || undefined,
      duration: sceneDuration(scene, selectedModel),
      resolution: sceneResolution(scene, selectedModel),
      aspect_ratio: sceneAspectRatio(scene, selectedModel),
      output_format: selectedModel.capabilities.default_output_format,
      generate_audio: selectedModel.capabilities.default_generate_audio,
      return_last_frame: draft.returnLastFrame,
      reference_media: draft.videoGenerationMode === 'reference'
        ? referencedVideoMedia(draft.prompt, draft.referenceMedia)
        : [],
    })).data
    videos.value[scene.id] = [result, ...(videos.value[scene.id] || [])]
    scene.metadata = { ...(scene.metadata || {}), current_video_id: result.id }
    while (alive && !terminalTaskStatuses.has(result.status)) {
      await sleep(4000)
      result = (await api.queryVideo(result.id)).data
      videos.value[scene.id] = videos.value[scene.id].map(item => item.id === result.id ? result : item)
    }
    if (!alive) return false
    const completed = result.status === TaskStatusEnum.COMPLETED
    if (completed) {
      setSceneVideoError(scene.id)
      syncInjectedLastFrame(result)
    } else {
      setSceneVideoError(scene.id, sceneVideoError(scene))
    }
    if (showNotice) {
      completed
        ? notice.success('分镜视频生成完成')
        : notice.error('视频生成失败，详情已显示在预览区')
    }
    return completed
  } catch (error) {
    const message = error instanceof Error ? error.message : '视频生成失败'
    setSceneVideoError(scene.id, message)
    if (showNotice) notice.error('视频生成失败，详情已显示在预览区')
    return false
  } finally {
    setSceneBusy(generatingVideoSceneIds, scene.id, false)
  }
}

async function refreshVideoHistory(scene: Scene) {
  if (refreshingVideoHistorySceneIds.value.has(scene.id)) return
  setSceneBusy(refreshingVideoHistorySceneIds, scene.id, true)
  try {
    const records = videos.value[scene.id] || []
    const pendingRecords = records.filter(record => !terminalTaskStatuses.has(record.status))
    if (pendingRecords.length) {
      await Promise.allSettled(pendingRecords.map(record => api.queryVideo(record.id)))
    }
    videos.value[scene.id] = (await api.videoGenerationHistory(scene.id)).data
    setSceneVideoError(scene.id)
  } catch (error) {
    notice.error(`刷新生成记录失败：${(error as Error).message}`)
  } finally {
    setSceneBusy(refreshingVideoHistorySceneIds, scene.id, false)
  }
}

async function selectVideoHistoryRecord(scene: Scene, record: VideoResult) {
  if (record.status !== TaskStatusEnum.COMPLETED || !record.url || record.id === currentVideoId(scene)) return
  try {
    await api.selectCurrentVideo(record.id)
    scene.metadata = { ...(scene.metadata || {}), current_video_id: record.id }
    setSceneVideoError(scene.id)
    notice.success('已切换为该次视频生成结果')
  } catch (error) {
    notice.error((error as Error).message)
  }
}

function syncInjectedLastFrame(result: VideoResult) {
  const metadata = result.metadata
  if (!metadata || typeof metadata !== 'object') return
  const targetSceneId = Number(metadata.last_frame_injected_scene_id)
  if (!Number.isInteger(targetSceneId) || targetSceneId < 1) return
  const reference = readReferenceMedia([metadata.last_frame_reference])[0]
  const targetScene = scenes.value.find(item => item.id === targetSceneId)
  if (!reference || !targetScene) return
  const draft = draftFor(targetScene)
  if (!draft.referenceMedia.some(item => item.type === 'image' && item.url === reference.url)) {
    draft.referenceMedia = [reference, ...draft.referenceMedia]
  }
  targetScene.metadata = {
    ...(targetScene.metadata || {}),
    video_reference_media: draft.referenceMedia,
  }
}

function batchVideoDisabledReason(scene: Scene) {
  const draft = draftFor(scene)
  const video = selectedVideoFor(scene)
  const model = selectedVideoModelConfig.value
  if (video?.status === TaskStatusEnum.COMPLETED) return '已完成'
  if (generatingVideoSceneIds.value.has(scene.id)) return '正在生成'
  if (!model) return '未配置视频模型'
  if (!model.capabilities.generation_modes.includes(draft.videoGenerationMode)) return '当前模型不支持该生成方式'
  if (!draft.prompt.trim()) return '提示词不完整'
  if (draft.videoGenerationMode === 'keyframes' && (!draft.firstFrameUrl || !draft.lastFrameUrl)) return '请先补全首尾帧'
  if (referenceLimitError(scene, model)) return referenceLimitError(scene, model)
  return ''
}

function openBatchVideoDialog() {
  const model = selectedVideoModelConfig.value
  if (!model || batchGeneratingVideos.value) {
    if (!model) notice.error('请先在设置中启用一个视频模型')
    return
  }
  if (!batchVideoSceneOptions.value.some(scene => !scene.disabled)) {
    notice.info('当前没有需要批量生成的视频')
    return
  }
  batchVideoDialogOpen.value = true
}

async function batchGenerateVideos(sceneIds: number[]) {
  const model = selectedVideoModelConfig.value
  if (!model || batchGeneratingVideos.value) return
  const selectedIdSet = new Set(sceneIds)
  const targets = scenes.value.filter(scene => selectedIdSet.has(scene.id) && !batchVideoDisabledReason(scene))
  if (!targets.length) {
    notice.info('所选分镜当前无法生成视频')
    return
  }

  batchVideoDialogOpen.value = false
  batchGeneratingVideos.value = true
  let nextIndex = 0
  let completedCount = 0
  const workerCount = Math.max(1, Math.min(model.concurrency, targets.length))
  const worker = async () => {
    while (nextIndex < targets.length) {
      const scene = targets[nextIndex++]
      if (scene && await generateVideo(scene, false)) completedCount += 1
    }
  }
  try {
    await Promise.all(Array.from({ length: workerCount }, worker))
    const failedCount = targets.length - completedCount
    failedCount
      ? notice.error(`批量生成完成：成功 ${completedCount} 条，失败 ${failedCount} 条`)
      : notice.success(`批量生成完成：成功 ${completedCount} 条`)
  } finally {
    batchGeneratingVideos.value = false
  }
}

function selectWorkspaceView(view: 'workflow' | 'storyboard') {
  if (workspaceView.value === view) return
  const query = { ...route.query }
  if (view === 'workflow') query.view = 'workflow'
  else delete query.view
  void router.replace({ query })
}

async function renameCanvas(name: string) {
  if (!activeChapter.value || savingCanvasIdentity.value) return
  savingCanvasIdentity.value = true
  try {
    const updated = (await api.updateChapter(activeChapter.value.id, { name })).data
    activeChapter.value = updated
    chapters.value = chapters.value.map(chapter => chapter.id === updated.id ? updated : chapter)
    notice.success('画布名称已保存')
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '画布名称保存失败')
  } finally {
    savingCanvasIdentity.value = false
  }
}

function openChapterDetails() {
  if (activeChapter.value) chapterDetailOpen.value = true
}

async function saveChapterDetails(value: { name: string; content: string }) {
  if (!activeChapter.value || savingChapterDetails.value) return
  savingChapterDetails.value = true
  try {
    const updated = (await api.updateChapter(activeChapter.value.id, value)).data
    activeChapter.value = updated
    chapters.value = chapters.value.map(chapter => chapter.id === updated.id ? updated : chapter)
    chapterDetailOpen.value = false
    notice.success('章节详情已保存')
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '章节详情保存失败')
  } finally {
    savingChapterDetails.value = false
  }
}

onMounted(load)
onMounted(() => {
  window.addEventListener('pointerdown', closeAssetActionsFromOutside)
  window.addEventListener('keydown', closeAssetActionsFromEscape)
})
onBeforeUnmount(() => {
  void flushPendingSceneSaves()
  alive = false
  chapterToolbarObserver?.disconnect()
  sceneScrollContainer?.removeEventListener('scroll', handleSceneScroll)
  if (sceneScrollFrame) cancelAnimationFrame(sceneScrollFrame)
  if (sceneScrollUnlockTimer) clearTimeout(sceneScrollUnlockTimer)
  window.removeEventListener('pointerdown', closeAssetActionsFromOutside)
  window.removeEventListener('keydown', closeAssetActionsFromEscape)
})
</script>

<template>
  <main class="storyboard-page" :class="{ 'is-workflow-view': workspaceView === 'workflow' }">
    <ShortDramaWorkspaceShell
      :project-id="projectId"
      :project-name="project?.name || '短剧项目'"
      :aspect-ratio="project?.aspectRatio || '9:16'"
      :resolution="project?.resolution || '720p'"
      :style-name="project?.style || '写实通用'"
      active-phase="storyboard"
      :creation-mode="project?.creationMode || 'agent'"
      :chapters="chapters"
      :active-chapter-id="activeChapterId"
      :video-enabled="videoPageEnabled"
      :show-episode-rail="workspaceView === 'storyboard'"
      :show-project-meta="workspaceView === 'storyboard'"
      :immersive="workspaceView === 'workflow'"
      @select-chapter="selectChapter"
    >
      <template v-if="workspaceView === 'workflow' && activeChapter" #project-name>
        <WorkbenchCanvasIdentity :name="stripChapterOrdinal(activeChapter.name) || '未命名'" :chapter-number="activeChapter.number" :saving="savingCanvasIdentity" @rename="renameCanvas" />
      </template>
      <template #header-end>
        <nav class="workspace-view-switch" aria-label="工作区视图切换">
          <AppButton variant="ghost" size="sm" :active="workspaceView === 'workflow'" :aria-pressed="workspaceView === 'workflow'" @click="selectWorkspaceView('workflow')"><Workflow :size="14" />工作流</AppButton>
          <AppButton variant="ghost" size="sm" :active="workspaceView === 'storyboard'" :aria-pressed="workspaceView === 'storyboard'" @click="selectWorkspaceView('storyboard')"><PanelsTopLeft :size="14" />故事板</AppButton>
        </nav>
      </template>

      <div class="storyboard-shell">

      <section class="storyboard-main" :class="{ 'is-workflow-view': workspaceView === 'workflow' }">
        <ShortDramaSceneStatusRail
          v-if="workspaceView === 'storyboard'"
          :items="sceneStatusItems"
          :active-scene-id="activeSceneId"
          :style="{ '--short-drama-scene-status-offset': `${chapterToolbarHeight}px` }"
          @select="selectSceneById"
        />
        <header v-if="workspaceView === 'storyboard'" class="chapter-toolbar">
          <button type="button" class="chapter-summary" :disabled="!activeChapter" aria-label="查看并编辑当前章节详情" @click="openChapterDetails">
            <span :class="{ 'is-agent': isAgent }">{{ isAgent ? 'AGENT STORYBOARD' : 'MANUAL STORYBOARD' }}</span>
            <h1>{{ activeChapter ? episodeDisplayLabel(activeChapter) : '分镜制作' }}</h1>
            <p>{{ activeChapter?.content?.slice(0, 120) }}</p>
            <small>点击查看详情</small>
          </button>
          <div class="chapter-actions">
            <AppSelect v-model="selectedVideoModel" class="chapter-model-select" density="compact" ariaLabel="视频模型" :options="videoModelOptions" :menu-width="300" align="end" />
            <AppButton v-if="isAgent" variant="secondary" size="sm" :loading="generatingStoryboard" @click="regenerateStoryboard"><Sparkles v-if="!generatingStoryboard" :size="15" />{{ generatingStoryboard ? 'Agent 生成中' : '重新生成分镜' }}</AppButton>
            <AppButton v-if="!isAgent" variant="secondary" size="sm" type="button" :loading="creatingManualScene" @click="createManualScene()"><Plus v-if="!creatingManualScene" :size="15" />{{ creatingManualScene ? "创建中" : "创建分镜" }}</AppButton>
            <AppButton variant="primary" size="sm" :loading="batchGeneratingVideos" @click="openBatchVideoDialog"><Clapperboard v-if="!batchGeneratingVideos" :size="15" />{{ batchGeneratingVideos ? '批量生成中' : '批量生视频' }}</AppButton>
          </div>
        </header>

        <div v-if="loading || generatingStoryboard || waitingAnalysis" class="storyboard-state"><LoaderCircle class="storyboard-state__spinner" :size="28" /><strong>{{ generatingStoryboard ? `Agent 正在生成第 ${activeChapter?.number || '-'} 集的全部分镜` : waitingAnalysis ? '项目分析尚未完成' : `正在读取第 ${activeChapter?.number || '-'} 集分镜` }}</strong><p>{{ generatingStoryboard ? '仅处理当前选中的这一集，不会自动生成其他集。' : waitingAnalysis ? 'AI 正在理解书稿并生成封面，完成后将自动生成本集分镜，请稍候…' : '正在准备本集章节、资产和视频信息。' }}</p></div>
        <div v-else-if="generationError && !scenes.length" class="storyboard-state is-error"><Clapperboard :size="28" /><strong>暂时无法生成分镜</strong><p>{{ generationError }}</p><AppButton variant="primary" size="sm" @click="isAgent ? generateChapterStoryboard(activeChapterId) : createManualScene()">重试</AppButton></div>
        <div v-else-if="!isAgent && !scenes.length" class="storyboard-state"><Clapperboard :size="28" /><strong>还没有分镜</strong><p>从第一个分镜开始，逐步搭建你的镜头列表。</p><AppButton variant="primary" size="sm" :loading="creatingManualScene" @click="createManualScene()"><Plus v-if="!creatingManualScene" :size="15" />{{ creatingManualScene ? "创建中" : "创建第一个分镜" }}</AppButton></div>
        <div v-else-if="workspaceView === 'workflow'" class="workflow-canvas-shell">
          <CreativeCanvas :key="`workflow-${activeChapterId}`" :novel-id="projectId" :chapter-id="activeChapterId" :aspect-ratio="project?.aspectRatio || '9:16'" :resolution="project?.resolution || '720p'" />
        </div>
        <div v-else class="shot-editor-list">
          <article v-for="scene in scenes" :id="`scene-${scene.id}`" :key="scene.id" class="shot-editor" :class="{ 'is-active': activeSceneId === scene.id }" :data-scene-id="scene.id">
            <header class="shot-editor-header">
              <div class="shot-editor-heading">
                <GripVertical class="drag-mark" :size="16" /><strong>分镜 {{ scene.sequence }}</strong><small>ID {{ scene.id }}</small>
                <nav aria-label="视频生成方式">
                  <AppButton variant="soft" size="sm" :active="draftFor(scene).videoGenerationMode === 'reference'" :aria-pressed="draftFor(scene).videoGenerationMode === 'reference'" @click="setVideoGenerationMode(scene, 'reference')"><span class="mode-dot" />全能参考生视频</AppButton>
                  <AppButton variant="soft" size="sm" :active="draftFor(scene).videoGenerationMode === 'keyframes'" :aria-pressed="draftFor(scene).videoGenerationMode === 'keyframes'" @click="setVideoGenerationMode(scene, 'keyframes')"><span class="mode-dot" />首尾帧生视频</AppButton>
                </nav>
              </div>
              <div>
                <AppButton variant="ghost" size="sm" icon-only :aria-label="`在分镜 ${scene.sequence} 下方添加分镜`" title="在下方添加分镜" @click="insertSceneAfter(scene)"><Plus :size="15" /></AppButton>
                <AppButton variant="ghost" size="sm" icon-only aria-label="复制分镜" title="复制分镜" @click="duplicateScene(scene)"><Copy :size="15" /></AppButton>
                <AppButton variant="danger" size="sm" icon-only aria-label="删除分镜" title="删除分镜" @click="removeScene(scene)"><Trash2 :size="15" /></AppButton>
              </div>
            </header>

            <div class="shot-editor-grid">
              <aside class="shot-info-panel">
                <h2>分镜信息</h2>
                <label><span>分镜描述</span><textarea :value="draftFor(scene).description" rows="5" placeholder="请输入分镜描述" @input="updateSceneText(scene, 'description', $event)" /></label>
                <section v-for="group in assetGroups" :key="group.type" class="shot-assets">
                  <header><span><component :is="group.icon" :size="15" />{{ group.label }}</span><span><small>{{ selectedAssetsFor(scene, group).length }}/{{ group.items.length }}</small><AppButton :id="`asset-picker-trigger-${assetPickerKey(scene, group.type)}`" variant="ghost" size="sm" icon-only :aria-label="`选择${group.label}及衍生状态`" @click="toggleAssetPicker(scene, group.type)"><Plus :size="15" /></AppButton></span></header>
                  <div
                    v-if="selectedAssetsFor(scene, group).length"
                    class="selected-assets"
                    :class="{
                      'is-person-assets': group.type === AssetTypeEnum.PERSON,
                      'is-scene-assets': group.type === AssetTypeEnum.SCENE,
                      'is-prop-assets': group.type === AssetTypeEnum.ITEM,
                    }"
                  >
                    <article v-for="asset in selectedAssetsFor(scene, group)" :key="asset.id" class="selected-asset-row">
                      <span
                        class="asset-thumb"
                        :class="{ 'is-reference-highlighted': highlightedReferenceKey === `asset:${scene.id}:${asset.id}` }"
                        :data-reference-asset-id="asset.id"
                      ><img v-if="selectedAssetImage(scene, asset)" :src="selectedAssetImage(scene, asset)" :alt="selectedAssetLabel(scene, asset)" /><component v-else :is="group.icon" :size="16" /></span>
                      <AppButton
                        :id="assetRowPickerAnchorId(scene, asset)"
                        variant="soft"
                        size="sm"
                        class="asset-name-button"
                        :active="openAssetPickerKey === assetPickerKey(scene, group.type) && assetPickerReplaceAssetIds[assetPickerKey(scene, group.type)] === asset.id"
                        :aria-expanded="openAssetPickerKey === assetPickerKey(scene, group.type) && assetPickerReplaceAssetIds[assetPickerKey(scene, group.type)] === asset.id"
                        :aria-label="`替换${selectedAssetLabel(scene, asset)}`"
                        :title="`替换${selectedAssetLabel(scene, asset)}`"
                        @click="toggleAssetReplacementPicker(scene, group.type, asset)"
                      ><span>{{ selectedAssetLabel(scene, asset) }}</span></AppButton>
                      <AppButton v-if="group.type === AssetTypeEnum.PERSON" variant="soft" size="sm" class="asset-voice-button"><Volume2 :size="13" /><span>未配置音色</span></AppButton>
                      <SceneAssetActionMenu
                        :open="openAssetActionKey === assetActionKey(scene, asset)"
                        :label="asset.canonical_name"
                        @toggle="toggleAssetActionMenu(scene, asset)"
                        @edit="editSceneAsset(asset)"
                        @remove="removeAssetFromScene(scene, asset)"
                      />
                    </article>
                  </div>
                  <p v-else>暂未选择{{ group.label.replace('分镜', '').replace('出镜', '') }}</p>
                  <SceneAssetVariantPicker
                    :open="openAssetPickerKey === assetPickerKey(scene, group.type)"
                    :anchor-id="assetPickerAnchorId(scene, group.type)"
                    :label="group.label"
                    :assets="group.items"
                    :selected-asset-ids="draftFor(scene).selectedAssetIds"
                    :selected-variant-ids="resolvedSelectedVariantIdsFor(scene)"
                    :initial-asset-id="assetPickerFocusIds[assetPickerKey(scene, group.type)] || 0"
                    :selection-mode="assetPickerReplaceAssetIds[assetPickerKey(scene, group.type)] ? 'replace' : 'add'"
                    :placement="assetPickerReplaceAssetIds[assetPickerKey(scene, group.type)] ? 'below' : 'auto'"
                    @close="closeAssetPicker(assetPickerKey(scene, group.type))"
                    @select="handleAssetPickerSelection(scene, group.type, $event)"
                  />
                </section>
              </aside>

              <section class="prompt-panel" :class="{ 'has-keyframes': draftFor(scene).videoGenerationMode === 'keyframes' }">
                <header><div><span><strong>分镜视频生成</strong><small>组合角色、场景和动作，生成连续镜头</small></span></div></header>
                <div v-if="draftFor(scene).videoGenerationMode === 'keyframes'" class="keyframe-inputs">
                  <label :class="{ 'has-image': draftFor(scene).firstFrameUrl }"><input type="file" accept="image/png,image/jpeg,image/webp" @change="uploadFrame(scene, 'first', $event)" /><img v-if="draftFor(scene).firstFrameUrl" :src="draftFor(scene).firstFrameUrl" alt="首帧" /><span v-else><LoaderCircle v-if="uploadingFrameKey === `${scene.id}:first`" :size="18" /><Upload v-else :size="18" /><strong>上传首帧</strong><small>视频开始画面</small></span><i>首帧</i></label>
                  <span>→</span>
                  <label :class="{ 'has-image': draftFor(scene).lastFrameUrl }"><input type="file" accept="image/png,image/jpeg,image/webp" @change="uploadFrame(scene, 'last', $event)" /><img v-if="draftFor(scene).lastFrameUrl" :src="draftFor(scene).lastFrameUrl" alt="尾帧" /><span v-else><LoaderCircle v-if="uploadingFrameKey === `${scene.id}:last`" :size="18" /><Upload v-else :size="18" /><strong>上传尾帧</strong><small>视频结束画面</small></span><i>尾帧</i></label>
                </div>
                <SceneReferenceMediaBar
                  :model="selectedVideoModelConfig"
                  :media="draftFor(scene).referenceMedia"
                  :asset-image-count="selectedAssetReferenceImageCount(scene)"
                  :highlighted-media-index="highlightedMediaIndex(scene)"
                  :disabled="draftFor(scene).videoGenerationMode === 'keyframes'"
                  :uploading="uploadingReferenceSceneIds.has(scene.id)"
                  @upload="uploadReferenceMedia(scene, $event)"
                  @remove="removeReferenceMedia(scene, $event)"
                />
                <ScenePromptEditor
                  :model-value="draftFor(scene).prompt"
                  :options="promptMentionOptions(scene)"
                  embedded
                  @update:model-value="updateScenePrompt(scene, $event)"
                />
                <footer>
                  <div>
                    <AppSelect v-model="selectedVideoModel" class="video-model-select" density="compact" ariaLabel="视频模型" :options="videoModelOptions" :menu-width="videoModelSelectWidth" :style="{ width: `${videoModelSelectWidth}px`, minWidth: `${videoModelSelectWidth}px` }" />
                    <SceneVideoParameterPicker
                      :model="selectedVideoModelConfig"
                      :mode="draftFor(scene).videoGenerationMode"
                      :duration="sceneDuration(scene)"
                      :resolution="sceneResolution(scene)"
                      :aspect-ratio="sceneAspectRatio(scene)"
                      :return-last-frame="draftFor(scene).returnLastFrame"
                      @update:duration="updateSceneDraft(scene, 'duration', $event)"
                      @update:resolution="updateSceneDraft(scene, 'videoResolution', $event)"
                      @update:aspect-ratio="updateSceneDraft(scene, 'videoAspectRatio', $event)"
                      @update:return-last-frame="updateSceneDraft(scene, 'returnLastFrame', $event)"
                    />
                  </div>
                  <AppButton variant="primary" size="md" aria-label="生成视频" :disabled="!canGenerateSceneVideo(scene)" :loading="generatingVideoSceneIds.has(scene.id)" @click="generateVideo(scene)"><Sparkles v-if="!generatingVideoSceneIds.has(scene.id)" :size="14" />{{ generatingVideoSceneIds.has(scene.id) ? '生成中' : '生成' }}<BillingPriceTag v-if="!generatingVideoSceneIds.has(scene.id)" :cost="sceneVideoEstimate(scene)" :pricing="selectedVideoModelConfig?.pricing" /></AppButton>
                </footer>
              </section>

              <aside class="preview-panel">
                <header><strong>视频预览</strong><RefreshCw :size="15" /></header>
                <div class="preview-stage">
                  <VideoGenerationErrorState
                    v-if="sceneVideoError(scene)"
                    :error="sceneVideoError(scene)"
                    :busy="generatingVideoSceneIds.has(scene.id)"
                    :reference="problemImageReference(scene)"
                    @retry="generateVideo(scene)"
                    @locate-reference="locateProblemImageReference(scene, $event)"
                  />
                  <video v-else-if="selectedVideoFor(scene)?.url" :src="selectedVideoFor(scene)?.url" controls playsinline />
                  <div v-else-if="generatingVideoSceneIds.has(scene.id) || (selectedVideoFor(scene) && !terminalTaskStatuses.has(selectedVideoFor(scene)!.status))" class="preview-empty is-running"><LoaderCircle :size="30" /><strong>视频生成中</strong><span>完成后将在这里自动播放</span></div>
                  <div v-else class="preview-empty"><MonitorPlay :size="32" /><strong>等待生成视频</strong><span>完善提示词后点击“生成视频”</span></div>
                </div>
                <SceneVideoGenerationHistory
                  :records="videos[scene.id] || []"
                  :current-id="currentVideoId(scene)"
                  :busy="refreshingVideoHistorySceneIds.has(scene.id)"
                  @refresh="refreshVideoHistory(scene)"
                  @select="selectVideoHistoryRecord(scene, $event)"
                  @retry="generateVideo(scene)"
                />
              </aside>
            </div>
          </article>
        </div>
      </section>
      <ChapterDetailDrawer
        :open="chapterDetailOpen"
        :chapter-number="activeChapter?.number || 0"
        :title="activeChapter ? stripChapterOrdinal(activeChapter.name) : ''"
        :content="activeChapter?.content || ''"
        :saving="savingChapterDetails"
        @close="chapterDetailOpen = false"
        @save="saveChapterDetails"
      />
      </div>
    </ShortDramaWorkspaceShell>
    <ShortDramaBatchVideoDialog
      :open="batchVideoDialogOpen"
      :scenes="batchVideoSceneOptions"
      :cost-by-scene="batchVideoCostByScene"
      :pricing="selectedVideoModelConfig?.pricing"
      @close="batchVideoDialogOpen = false"
      @generate="batchGenerateVideos"
    />
    <AssetCreateDialog
      :open="Boolean(editingAsset)"
      :kind="editingAssetKind(editingAsset)"
      :novel-id="projectId"
      :asset="editingAsset"
      :chapter-number="activeChapter?.number"
      :episode-numbers="chapters.map(item => item.number)"
      @close="closeAssetEditor"
      @saved="saveEditedAsset"
    />
  </main>
</template>

<style scoped>
.storyboard-page { min-width: 0; min-height: 100%; overflow-x: clip; color: #303442; background: #f7f8fb; }
.storyboard-page.is-workflow-view { height: 100vh; overflow: hidden; }
.storyboard-shell { min-height: calc(100vh - 72px); }
.storyboard-page.is-workflow-view .storyboard-shell { height: 100vh; min-height: 0; }
.storyboard-main { min-width: 0; padding: 16px 16px 42px; }
.storyboard-main.is-workflow-view { height: 100%; padding: 0; }
.chapter-toolbar { position: sticky; top: var(--short-drama-header-height,72px); z-index: 19; display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 24px; margin: -16px -16px 2px; padding: 5px; background: var(--app-surface-muted, #f7f8fb); color: var(--app-text, #303442); }
.chapter-summary { position: relative; display: block; min-width: 0; max-width: min(840px,calc(100% - 540px)); padding: 4px 30px 4px 5px; overflow: hidden; border: 0; border-radius: 10px; outline: 0; color: inherit; background: transparent; font: inherit; text-align: left; cursor: pointer; transition: background-color .16s ease,box-shadow .16s ease; }
.chapter-summary:hover { background: rgb(255 255 255 / 72%); box-shadow: inset 0 0 0 1px #eceef5; }
.chapter-summary:focus-visible { outline: 3px solid rgb(91 92 246 / 18%); outline-offset: 1px; }
.chapter-summary:disabled { cursor: default; }
.chapter-summary > span { color: #8c91a0; font-size: 8px; font-weight: 750; letter-spacing: .15em; }
.chapter-summary > span.is-agent { color: #6163ef; }
.chapter-summary > small { position: absolute; top: 9px; right: 8px; color: #7379ef; font-size: 8px; font-weight: 650; opacity: 0; transform: translateX(4px); transition: opacity .16s ease,transform .16s ease; }
.chapter-summary:hover > small,.chapter-summary:focus-visible > small { opacity: 1; transform: translateX(0); }
.chapter-toolbar h1 { margin: 5px 0 6px; font-size: 19px; color: var(--app-text, #303442); }
.chapter-toolbar p { max-width: 760px; margin: 0; overflow: hidden; color: var(--app-text-muted, #898f9e); font-size: 10px; line-height: 1.6; text-overflow: ellipsis; white-space: nowrap; }
.chapter-actions { display: flex; flex: 0 0 auto; align-self: center; align-items: center; justify-content: flex-end; gap: 8px; margin-left: auto; }
.chapter-model-select { width: 300px; min-width: 300px; }
.video-model-select { max-width: min(420px, 48vw); }
.video-model-select :deep(.app-select__value) { overflow: visible; text-overflow: clip; }
.workspace-view-switch { grid-column: 3; display: flex; justify-self: end; align-items: center; gap: 3px; padding: 3px; border-radius: 11px; background: #f1f2f7; box-shadow: inset 0 0 0 1px #e5e7ef; }
.workspace-view-switch button { min-height: 32px; gap: 6px; padding-inline: 11px; border-radius: 8px; color: #777d8d; background: transparent; box-shadow: none; font-size: 11px; }
.workspace-view-switch button:hover { color: #575d6d; background: rgb(255 255 255 / 68%); }
.workspace-view-switch button.is-active { color: #5759eb; background: #fff; box-shadow: 0 3px 10px rgb(47 50 80 / 9%); }
.workspace-view-switch button:focus-visible { outline: 2px solid rgb(91 92 246 / 22%); outline-offset: 1px; }
.storyboard-page.is-workflow-view .workspace-view-switch { grid-column: 2; pointer-events: auto; background: rgb(33 30 27 / 92%); box-shadow: inset 0 0 0 1px #3b3631, 0 8px 24px rgb(0 0 0 / 24%); backdrop-filter: blur(12px); }
.storyboard-page.is-workflow-view .workspace-view-switch button { color: #c7bdb4; }
.storyboard-page.is-workflow-view .workspace-view-switch button:hover { color: #eee9e2; background: #2a2622; }
.storyboard-page.is-workflow-view .workspace-view-switch button.is-active { color: #eee9e2; background: #3a354f; box-shadow: inset 0 0 0 1px rgb(169 149 255 / 22%); }
.storyboard-page.is-workflow-view .workspace-view-switch button:focus-visible { outline-color: rgb(169 149 255 / 34%); }
.workflow-canvas-shell { width: 100%; height: 100%; min-height: 0; overflow: hidden; background: #151412; }
.storyboard-state { display: grid; min-height: calc(100vh - 210px); place-items: center; align-content: center; gap: 8px; color: #686ef1; text-align: center; }
.storyboard-state__spinner { animation: spin 1s linear infinite; }
.storyboard-state strong { color: #454a59; font-size: 14px; }
.storyboard-state p { max-width: 460px; margin: 0; color: #9297a6; font-size: 11px; }
.storyboard-state.is-error svg { color: #bf6470; animation: none; }
.storyboard-state button { margin-top: 8px; }
.shot-editor-list { display: grid; gap: 12px; }
.shot-editor { overflow: hidden; scroll-margin-top: calc(var(--short-drama-header-height,72px) + 116px); border-radius: 16px; background: #fff; box-shadow: inset 0 0 0 1px #e9ebf2; }
.shot-editor.is-active { box-shadow: inset 0 0 0 1px #dfe1f5; }
.shot-editor-header { display: flex; min-height: 48px; align-items: center; justify-content: space-between; padding: 0 12px; background: #fbfbfd; }
.shot-editor-header > div { display: flex; align-items: center; gap: 7px; }
.shot-editor-heading > nav { display: flex; align-items: center; gap: 2px; margin-left: 8px; padding: 3px; border-radius: 9px; background: #f1f2f7; }
.shot-editor-heading > nav button { min-height: 28px; padding-inline: 9px; color: #747a89; background: transparent; box-shadow: none; font-size: 9px; }
.shot-editor-heading > nav button.is-active { color: #5658ea; background: #fff; box-shadow: 0 2px 8px rgb(46 49 70 / 7%); }
.mode-dot { width: 11px; height: 11px; border: 1px solid #d9dce6; border-radius: 50%; background: #fff; }
.shot-editor-heading > nav button.is-active .mode-dot { border: 3px solid #6264ef; }
.shot-editor-header strong { font-size: 12px; }
.shot-editor-header small { padding: 3px 5px; border-radius: 5px; color: #7476df; background: #efefff; font-size: 8px; }
.drag-mark { color: #9ba0ae; font-size: 17px; }
.shot-editor-grid { display: grid; min-height: 630px; grid-template-columns: 410px minmax(600px,3fr) minmax(520px,2fr); gap: 12px; padding: 12px; background: #f8f9fc; }
.shot-info-panel,.prompt-panel,.preview-panel { min-width: 0; border-radius: 12px; background: #fff; box-shadow: inset 0 0 0 1px #e7e9f0; }
.shot-info-panel { display: grid; align-content: start; gap: 16px; padding: 16px; overflow-y: auto; scrollbar-width: none; }
.shot-info-panel::-webkit-scrollbar { display: none; }
.shot-info-panel h2,.prompt-panel strong,.preview-panel strong { margin: 0; font-size: 13px; }
.shot-info-panel label { display: grid; gap: 7px; color: #686e7d; font-size: 10px; }
.shot-info-panel textarea,.prompt-panel textarea { width: 100%; border: 0; outline: 0; color: #3e4351; background: #f7f8fb; font: inherit; resize: none; }
.shot-info-panel textarea { padding: 11px; border-radius: 9px; font-size: 11px; line-height: 1.65; box-shadow: inset 0 0 0 1px #e1e4ec; }
.shot-info-panel textarea:focus,.prompt-panel textarea:focus { box-shadow: inset 0 0 0 2px rgb(91 92 246 / 14%); }
.shot-assets { display: grid; gap: 8px; }
.shot-assets > header { display: flex; align-items: center; justify-content: space-between; color: #525867; font-size: 10px; font-weight: 650; }
.shot-assets > header > span { display: inline-flex; align-items: center; gap: 6px; }
.shot-assets > header > span:last-child { display: flex; align-items: center; gap: 2px; }
.shot-assets > header small { color: #9a9fac; font-weight: 400; }
.shot-assets > header button { width: 26px; min-height: 26px; padding: 0; }
.selected-assets { display: grid; gap: 7px; }
.selected-asset-row { display: grid; min-width: 0; grid-template-columns: 38px minmax(0,1fr) 30px; align-items: center; gap: 6px; }
.selected-assets.is-person-assets .selected-asset-row { grid-template-columns: 38px minmax(0,1fr) 116px 30px; }
.selected-asset-row > button { min-width: 0; justify-content: flex-start; }
.selected-asset-row .asset-name-button { padding-inline: 9px; color: #4c5261; background: #fff; box-shadow: inset 0 0 0 1px #e0e3eb; }
.selected-asset-row .asset-name-button span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.selected-asset-row .asset-voice-button { color: #a0a5b2; background: #fafbfc; box-shadow: inset 0 0 0 1px #eceef3; font-size: 9px; }
.selected-assets.is-scene-assets { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 8px; }
.selected-assets.is-scene-assets .selected-asset-row { grid-template-columns: minmax(0,1fr) 30px; align-items: end; }
.selected-assets.is-scene-assets .asset-thumb { grid-column: 1 / -1; width: 100%; height: auto; aspect-ratio: 16 / 9; border-radius: 10px; }
.selected-assets.is-scene-assets .asset-name-button { grid-column: 1; }
.asset-thumb { display: grid; width: 38px; height: 38px; flex: 0 0 38px; overflow: hidden; place-items: center; border-radius: 7px; color: #959baa; background: #e9ebf1; transition: box-shadow .18s ease, transform .18s ease; }
.asset-thumb.is-reference-highlighted { box-shadow: 0 0 0 3px rgb(255 122 140 / 42%), 0 6px 18px rgb(120 35 52 / 18%); transform: scale(1.04); }
.asset-thumb img { width: 100%; height: 100%; object-fit: cover; }
.shot-assets > p { display: grid; min-height: 52px; margin: 0; place-items: center; border-radius: 9px; color: #a1a6b3; background: #f7f8fb; font-size: 9px; }
.asset-picker { display: grid; max-height: 180px; gap: 4px; overflow-y: auto; padding: 6px; border-radius: 10px; background: #f7f8fb; }
.asset-picker button { width: 100%; justify-content: flex-start; color: #646a79; }
.asset-picker button > span:nth-child(2) { min-width: 0; flex: 1; overflow: hidden; text-align: left; text-overflow: ellipsis; white-space: nowrap; }
.asset-picker-thumb { display: grid; width: 26px; height: 26px; overflow: hidden; place-items: center; border-radius: 6px; background: #e8eaf0; }
.asset-picker-thumb img { width: 100%; height: 100%; object-fit: cover; }
.prompt-panel { display: grid; grid-template-rows: auto auto minmax(0,1fr) auto; overflow: hidden; border: 1px solid var(--app-border); background: var(--app-surface); box-shadow: 0 8px 24px rgb(25 30 46 / 3%); transition: border-color .18s ease,box-shadow .18s ease; }
.prompt-panel:focus-within { border-color: color-mix(in srgb,var(--app-accent) 52%,var(--app-border)); box-shadow: 0 0 0 3px color-mix(in srgb,var(--app-accent) 8%,transparent),0 10px 28px rgb(25 30 46 / 4%); }
.prompt-panel.has-keyframes { grid-template-rows: auto auto auto minmax(0,1fr) auto; }
.prompt-panel > header { display: flex; min-height: 62px; align-items: center; justify-content: space-between; padding: 0 16px; }
.prompt-panel > header > div { display: flex; min-width: 0; align-items: center; gap: 10px; color: var(--app-text); }
.prompt-panel > header span { display: grid; min-width: 0; gap: 3px; }
.prompt-panel > header small { color: var(--app-text-muted); font-size: 9px; font-weight: 400; }
.keyframe-inputs { display: grid; grid-template-columns: minmax(0,1fr) auto minmax(0,1fr); align-items: center; gap: 10px; padding: 0 16px 14px; }
.keyframe-inputs > span { color: #a0a5b2; font-size: 16px; }
.keyframe-inputs label { position: relative; display: grid; min-height: 112px; overflow: hidden; place-items: center; border-radius: 12px; color: #858b9a; background: #f7f8fb; box-shadow: inset 0 0 0 1px #e8eaf1; cursor: pointer; }
.keyframe-inputs label:hover { color: #5d5fee; background: #f4f4ff; box-shadow: inset 0 0 0 1px #cdcffa; }
.keyframe-inputs input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.keyframe-inputs img { width: 100%; height: 112px; object-fit: cover; }
.keyframe-inputs label > span { display: grid; place-items: center; gap: 4px; }
.keyframe-inputs label > span svg { margin-bottom: 2px; }
.keyframe-inputs label > span strong { color: currentColor; font-size: 11px; }
.keyframe-inputs label > span small { color: #a1a6b3; font-size: 9px; }
.keyframe-inputs label > i { position: absolute; top: 8px; left: 8px; padding: 4px 7px; border-radius: 7px; color: #5e60e9; background: rgb(255 255 255 / 92%); box-shadow: 0 3px 10px rgb(37 40 58 / 8%); font-size: 9px; font-style: normal; font-weight: 700; }
.prompt-panel > textarea { min-height: 420px; padding: 8px 16px 18px; background: #fff; font-size: 11px; line-height: 1.8; white-space: pre-wrap; }
.prompt-panel > footer { display: flex; min-height: 58px; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 14px 12px; border-top: 0; background: transparent; }
.prompt-panel > footer > div { display: flex; min-width: 0; align-items: center; gap: 6px; }
.prompt-panel > footer > div > span { display: inline-flex; min-height: 34px; align-items: center; gap: 4px; padding: 0 10px; border-radius: 9px; color: #777d8d; background: #fff; box-shadow: 0 1px 3px rgb(35 39 55 / 8%); font-size: 10px; }
.prompt-panel input { width: 23px; padding: 0; border: 0; outline: 0; color: #555b6a; background: transparent; font: inherit; text-align: right; }
.preview-panel { display: grid; grid-template-rows: 48px minmax(0,1fr) auto; overflow: hidden; }
.preview-panel > header { display: flex; align-items: center; justify-content: space-between; padding: 0 15px; }
.preview-panel > header svg { color: #9197a6; }
.preview-stage { display: grid; min-height: 520px; overflow: hidden; place-items: center; background: #292e39; }
.preview-stage video { width: 100%; height: 100%; object-fit: contain; }
.preview-empty { display: grid; place-items: center; gap: 8px; color: #7f8798; text-align: center; }
.preview-empty svg { color: #8e96a8; }
.preview-empty strong { color: #c8ccd4; font-size: 12px; }
.preview-empty span { font-size: 9px; }
.preview-empty.is-running svg { color: #8587ff; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1180px) { .shot-editor-grid { grid-template-columns: 260px minmax(380px,1fr); }.preview-panel { grid-column: 1 / -1; }.preview-stage { min-height: 420px; max-height: 560px; } }
@media (max-width: 820px) { .workspace-view-switch { flex: 0 0 auto; }.storyboard-page.is-workflow-view .storyboard-shell { height: 100vh; }.storyboard-main { padding: 16px 14px 36px; }.storyboard-main.is-workflow-view { height: 100%; padding: 0; }.chapter-toolbar { align-items: stretch; flex-direction: column; margin-inline: -14px; padding-inline: 14px; }.chapter-summary { max-width: 100%; }.chapter-actions { width: 100%; justify-content: flex-end; overflow-x: auto; padding-bottom: 4px; }.chapter-model-select { width: min(300px,70vw); min-width: min(300px,70vw); }.workflow-canvas-shell { min-height: 520px; }.shot-editor { scroll-margin-top: calc(var(--short-drama-header-height,124px) + 180px); }.shot-editor-header { flex-wrap: wrap; gap: 6px; padding-block: 7px; }.shot-editor-header > nav { order: 3; width: 100%; }.shot-editor-grid { grid-template-columns: 1fr; }.preview-panel { grid-column: 1; }.shot-info-panel { max-height: none; }.prompt-panel > footer { align-items: stretch; flex-direction: column; }.prompt-panel > footer > div { overflow-x: auto; }.prompt-panel > footer > button { width: 100%; } }
@media (max-width: 520px) { .chapter-toolbar p { white-space: normal; }.shot-editor-grid { padding: 7px; }.prompt-panel > textarea { min-height: 320px; }.preview-stage { min-height: 360px; } }
@media (prefers-reduced-motion: reduce) { .storyboard-state svg,.preview-empty.is-running svg { animation-duration: 1.8s; } }
.scene-video-cost { margin-left: 6px; font-size: 10px; font-weight: 600; opacity: .85; }
</style>
