<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  Boxes,
  Check,
  ChevronDown,
  CircleAlert,
  Clock3,
  ImagePlus,
  Library,
  LoaderCircle,
  Maximize2,
  Pencil,
  Search,
  Sparkles,
  RefreshCw,
  Upload,
  Undo2,
  UserRound,
  Volume2,
  X,
} from 'lucide-vue-next'
import AppSelect from '@/components/AppSelect.vue'
import AssetVariantStrip from '@/components/AssetVariantStrip.vue'
import ImageAnnotationEditor from '@/components/ImageAnnotationEditor.vue'
import ImageLightbox from '@/components/ImageLightbox.vue'
import ImageGenerationParameterPanel, { type ImageGenerationParameters } from '@/components/ImageGenerationParameterPanel.vue'
import { api } from '@/api'
import { isAbortError, pollUntilTerminal } from '@/features/workbench/execution/workbenchAsync'
import { notice } from '@/shared/notice'
import { resolveCharacterFormMetadata } from '@/shared/characterMetadata'
import { AssetTypeEnum, TaskStatusEnum, type AiTask, type Asset, type AssetGenerationRecord, type AssetVariant, type AssetVariantDraft, type DigitalHuman, type ImageGenerationModel } from '@/types'

type AssetKind = 'character' | 'scene' | 'prop'
type CreateMode = 'ai' | 'library' | 'upload'
type LibraryItem = { key: string; name: string; detail: string; image: string; source: 'public' | 'project'; asset?: Asset; human?: DigitalHuman }
type LibraryScope = 'all' | 'public' | 'project'
type AssetEditorFormSnapshot = {
  version: 1
  canonical_name: string
  description: string
  base_traits: string
  prompt_touched: boolean
  creation_mode: CreateMode
  gender: string
  age_group: string
  voice: string
  reference_layout: string
  model_config_id: number | null
  image_parameters: {
    clarity: string
    aspect_ratio: string
    output_format: string
    generation_count: number
  }
  library_selection: {
    key: string
    scope: LibraryScope
  }
}

const VARIANT_EDITOR_FORM_KEY = 'editor_form'

const props = withDefaults(defineProps<{ open: boolean; kind: AssetKind; novelId: number; asset?: Asset | null; chapterNumber?: number; episodeNumbers?: number[]; initialMode?: CreateMode }>(), {
  episodeNumbers: () => [],
  initialMode: 'ai',
})
const emit = defineEmits<{ close: []; created: [asset: Asset]; saved: [asset: Asset] }>()

const config = computed(() => ({
  character: { label: '角色', icon: UserRound, type: AssetTypeEnum.PERSON, library: '角色库' },
  scene: { label: '场景', icon: ImagePlus, type: AssetTypeEnum.SCENE, library: '场景库' },
  prop: { label: '道具', icon: Boxes, type: AssetTypeEnum.ITEM, library: '道具库' },
})[props.kind])

const genderOptions = [
  { value: '', label: '请选择' },
  { value: '男', label: '男' },
  { value: '女', label: '女' },
  { value: '其他（动物）', label: '其他（动物）' },
]
const ageOptions = [
  { value: '', label: '请选择' },
  { value: '儿童', label: '儿童' },
  { value: '少年', label: '少年' },
  { value: '青年', label: '青年' },
  { value: '中年', label: '中年' },
  { value: '老年', label: '老年' },
]
const referenceLayoutOptions = [
  { value: 'character_turnaround', label: '单人多视图' },
  { value: 'group_portrait', label: '人物群像' },
]

const mode = ref<CreateMode>('ai')
const name = ref('')
const description = ref('')
const prompt = ref('')
const gender = ref('')
const age = ref('')
const voice = ref('')
const imageParameters = ref<ImageGenerationParameters>({ clarity: '1.5K', aspectRatio: '16:9', outputFormat: 'png', generationCount: 1 })
const referenceLayout = ref('character_turnaround')
const modelId = ref('')
const models = ref<ImageGenerationModel[]>([])
const libraryItems = ref<LibraryItem[]>([])
const selectedLibraryKey = ref('')
const libraryScope = ref<LibraryScope>('all')
const search = ref('')
const uploadFile = ref<File | null>(null)
const uploadPreview = ref('')
const dragging = ref(false)
const saving = ref(false)
const promptTouched = ref(false)
const promptLanguage = ref<'zh' | 'en'>('en')
const promptSourceAsset = ref<Asset | null>(null)
const loadingLibrary = ref(false)
const loadingMoreLibrary = ref(false)
const loadingHistory = ref(false)
const generationHistory = ref<AssetGenerationRecord[]>([])
const generationTask = ref<AiTask | null>(null)
const generationRequested = ref(false)
const generationError = ref('')
const selectedErrorRecordId = ref('')
const restoringRecordId = ref('')
const selectedVariant = ref<AssetVariant | null>(null)
const variantDraft = ref<AssetVariantDraft | null>(null)
const variantStripRef = ref<{ upsertVariant: (variant: AssetVariant) => void } | null>(null)
const imageInfo = ref<Record<string, { dimensions: string; format: string }>>({})
const lightboxImage = ref('')
const lightboxAlt = ref('')
const lightboxFormat = ref('')
const annotationOpen = ref(false)
const annotationSaving = ref(false)
const publicPage = ref(0)
const publicPages = ref(0)
const projectPage = ref(0)
const projectPages = ref(0)
let previousBodyOverflow = ''
let generationController: AbortController | null = null
const formDrafts = new Map<string, AssetEditorFormSnapshot>()
const isEditing = computed(() => Boolean(props.asset))
const variantContextActive = computed(() => Boolean(variantDraft.value))
const generatedImage = computed(() => variantDraft.value?.is_new
  ? ''
  : selectedVariant.value
    ? selectedVariant.value.images?.[0] || ''
    : promptSourceAsset.value?.main_image || props.asset?.main_image || '')
const currentImageName = computed(() => variantDraft.value?.name || selectedVariant.value?.name || name.value || props.asset?.canonical_name || config.value.label)
const currentImageFormat = computed(() => {
  const historyFormat = generationHistory.value.find(record => record.images.includes(generatedImage.value))?.output_format
  const sourceMetadata = selectedVariant.value?.metadata || props.asset?.metadata
  const metadata = sourceMetadata && typeof sourceMetadata === 'object'
    ? sourceMetadata as Record<string, unknown>
    : {}
  return historyFormat || (typeof metadata.output_format === 'string' ? metadata.output_format : '')
})
const selectedErrorRecord = computed(() => generationHistory.value.find(record => record.id === selectedErrorRecordId.value && record.error_message) || null)
const terminalGenerationStatuses = new Set<number>([
  TaskStatusEnum.COMPLETED,
  TaskStatusEnum.FAILED,
  TaskStatusEnum.CANCELLED,
])
const generationRunning = computed(() => Boolean(
  generationTask.value && !terminalGenerationStatuses.has(generationTask.value.status),
))
const generationBusy = computed(() => generationRequested.value && (saving.value || generationRunning.value))
const generationStatusText = computed(() => {
  if (generationError.value) return '生成失败'
  if (!generationTask.value) return '正在提交'
  return historyStatus(generationTask.value.status)
})
const generationStatusMessage = computed(() => {
  if (generationError.value) return generationError.value
  if (!generationTask.value) return '正在保存当前配置并创建生成任务…'
  if (generationTask.value.status === TaskStatusEnum.PENDING) return '任务已提交，正在等待模型执行。'
  if (generationTask.value.status === TaskStatusEnum.QUEUED) return '当前任务正在队列中，轮到后会自动开始。'
  if (generationTask.value.status === TaskStatusEnum.PROCESSING) return '正在生成图像，完成后这里会自动显示最新结果。'
  return ''
})
const historyStatus = (status: TaskStatusEnum) => ({
  [TaskStatusEnum.PENDING]: '等待中',
  [TaskStatusEnum.PROCESSING]: '生成中',
  [TaskStatusEnum.COMPLETED]: '已完成',
  [TaskStatusEnum.FAILED]: '失败',
  [TaskStatusEnum.CANCELLED]: '已取消',
  [TaskStatusEnum.QUEUED]: '排队中',
}[status] || '未知')

const modelOptions = computed(() => models.value.map(item => ({ value: String(item.config_id), label: item.name || item.model || `生图模型 ${item.config_id}` })))
const selectedModel = computed(() => models.value.find(item => String(item.config_id) === modelId.value) || null)
const filteredLibraryItems = computed(() => libraryItems.value.filter(item => {
  if (libraryScope.value !== 'all' && item.source !== libraryScope.value) return false
  const query = search.value.trim().toLowerCase()
  return !query || `${item.name} ${item.detail}`.toLowerCase().includes(query)
}))
const selectedLibrary = computed(() => libraryItems.value.find(item => item.key === selectedLibraryKey.value))
const publicHasMore = computed(() => props.kind === 'character' && publicPage.value < publicPages.value)
const projectHasMore = computed(() => projectPage.value < projectPages.value)
const isGroupPortrait = computed(() => props.kind === 'character' && referenceLayout.value === 'group_portrait')
const promptPlaceholder = computed(() => isGroupPortrait.value
  ? '描述群像中的人物、各自固定特征、服装与人物关系'
  : `描述${config.value.label}的外观、材质、光影和视角要求`)
const libraryHasMore = computed(() => {
  if (libraryScope.value === 'public') return publicHasMore.value
  if (libraryScope.value === 'project') return projectHasMore.value
  return publicHasMore.value || projectHasMore.value
})
const canSubmit = computed(() => {
  if (isEditing.value) return variantDraft.value ? Boolean(variantDraft.value.name.trim()) : Boolean(name.value.trim())
  if (mode.value === 'library') return Boolean(selectedLibrary.value)
  const characterReady = props.kind !== 'character' || isGroupPortrait.value || Boolean(gender.value && age.value)
  if (mode.value === 'upload') return Boolean(name.value.trim() && uploadFile.value && characterReady)
  return Boolean(name.value.trim() && prompt.value.trim() && characterReady && modelId.value)
})

function reset() {
  generationController?.abort()
  generationController = null
  formDrafts.clear()
  mode.value = props.initialMode
  name.value = ''
  description.value = ''
  prompt.value = ''
  promptTouched.value = false
  promptSourceAsset.value = null
  gender.value = ''
  age.value = ''
  voice.value = ''
  imageParameters.value = { clarity: '1.5K', aspectRatio: '16:9', outputFormat: 'png', generationCount: 1 }
  referenceLayout.value = 'character_turnaround'
  selectedLibraryKey.value = ''
  libraryScope.value = 'all'
  search.value = ''
  libraryItems.value = []
  publicPage.value = 0
  publicPages.value = 0
  projectPage.value = 0
  projectPages.value = 0
  uploadFile.value = null
  if (uploadPreview.value) URL.revokeObjectURL(uploadPreview.value)
  uploadPreview.value = ''
  modelId.value = ''
  generationHistory.value = []
  generationTask.value = null
  generationRequested.value = false
  generationError.value = ''
  selectedErrorRecordId.value = ''
  restoringRecordId.value = ''
  selectedVariant.value = null
  variantDraft.value = null
  imageInfo.value = {}
  lightboxImage.value = ''
  annotationOpen.value = false
  annotationSaving.value = false

  if (props.asset) {
    const metadata = props.asset.metadata && typeof props.asset.metadata === 'object'
      ? props.asset.metadata as Record<string, unknown>
      : {}
    name.value = props.asset.canonical_name || ''
    description.value = props.asset.description || ''
    prompt.value = props.asset.base_traits || ''
    const characterMetadata = resolveCharacterFormMetadata(props.asset)
    gender.value = characterMetadata.gender
    age.value = characterMetadata.ageGroup
    voice.value = typeof metadata.voice === 'string' ? metadata.voice : ''
    referenceLayout.value = metadata.reference_layout === 'group_portrait'
      ? 'group_portrait'
      : 'character_turnaround'
    imageParameters.value = {
      clarity: typeof metadata.clarity === 'string' ? metadata.clarity : typeof metadata.resolution === 'string' ? metadata.resolution : imageParameters.value.clarity,
      aspectRatio: typeof metadata.aspect_ratio === 'string' ? metadata.aspect_ratio : imageParameters.value.aspectRatio,
      outputFormat: typeof metadata.output_format === 'string' ? metadata.output_format.toLowerCase() : imageParameters.value.outputFormat,
      generationCount: Number(metadata.generation_count) || imageParameters.value.generationCount,
    }
    if (Number.isFinite(Number(metadata.model_config_id))) modelId.value = String(metadata.model_config_id)
  }
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function stringField(source: Record<string, unknown>, key: string, fallback: string) {
  return typeof source[key] === 'string' ? source[key] : fallback
}

function modeField(value: unknown, fallback: CreateMode): CreateMode {
  return value === 'ai' || value === 'library' || value === 'upload' ? value : fallback
}

function scopeField(value: unknown, fallback: LibraryScope): LibraryScope {
  return value === 'all' || value === 'public' || value === 'project' ? value : fallback
}

function captureFormSnapshot(): AssetEditorFormSnapshot {
  return {
    version: 1,
    canonical_name: name.value,
    description: description.value,
    base_traits: prompt.value,
    prompt_touched: promptTouched.value,
    creation_mode: mode.value,
    gender: gender.value,
    age_group: age.value,
    voice: voice.value,
    reference_layout: referenceLayout.value,
    model_config_id: Number(modelId.value) || null,
    image_parameters: {
      clarity: imageParameters.value.clarity,
      aspect_ratio: imageParameters.value.aspectRatio,
      output_format: imageParameters.value.outputFormat,
      generation_count: imageParameters.value.generationCount,
    },
    library_selection: {
      key: selectedLibraryKey.value,
      scope: libraryScope.value,
    },
  }
}

function snapshotForVariant(variant: AssetVariant, fallback: AssetEditorFormSnapshot): AssetEditorFormSnapshot {
  const metadata = asRecord(variant.metadata)
  const stored = asRecord(metadata[VARIANT_EDITOR_FORM_KEY])
  const storedImageParameters = asRecord(stored.image_parameters)
  const storedLibrarySelection = asRecord(stored.library_selection)
  const modelConfigId = stored.model_config_id ?? metadata.model_config_id
  return {
    version: 1,
    canonical_name: stringField(stored, 'canonical_name', fallback.canonical_name),
    description: stringField(stored, 'description', fallback.description),
    base_traits: stringField(stored, 'base_traits', variant.base_traits || fallback.base_traits),
    prompt_touched: typeof stored.prompt_touched === 'boolean' ? stored.prompt_touched : true,
    creation_mode: modeField(stored.creation_mode ?? metadata.creation_mode, fallback.creation_mode),
    gender: stringField(stored, 'gender', stringField(metadata, 'gender', fallback.gender)),
    age_group: stringField(stored, 'age_group', stringField(metadata, 'age_group', fallback.age_group)),
    voice: stringField(stored, 'voice', stringField(metadata, 'voice', fallback.voice)),
    reference_layout: stringField(stored, 'reference_layout', stringField(metadata, 'reference_layout', fallback.reference_layout)),
    model_config_id: Number.isFinite(Number(modelConfigId)) ? Number(modelConfigId) : fallback.model_config_id,
    image_parameters: {
      clarity: stringField(storedImageParameters, 'clarity', stringField(metadata, 'clarity', fallback.image_parameters.clarity)),
      aspect_ratio: stringField(storedImageParameters, 'aspect_ratio', stringField(metadata, 'aspect_ratio', fallback.image_parameters.aspect_ratio)),
      output_format: stringField(storedImageParameters, 'output_format', stringField(metadata, 'output_format', fallback.image_parameters.output_format)),
      generation_count: Number(storedImageParameters.generation_count ?? metadata.generation_count) || fallback.image_parameters.generation_count,
    },
    library_selection: {
      key: stringField(storedLibrarySelection, 'key', fallback.library_selection.key),
      scope: scopeField(storedLibrarySelection.scope, fallback.library_selection.scope),
    },
  }
}

function applyFormSnapshot(snapshot: AssetEditorFormSnapshot, isVariant: boolean) {
  name.value = snapshot.canonical_name
  description.value = snapshot.description
  prompt.value = snapshot.base_traits
  mode.value = snapshot.creation_mode
  gender.value = snapshot.gender
  age.value = snapshot.age_group
  voice.value = snapshot.voice
  referenceLayout.value = snapshot.reference_layout
  modelId.value = snapshot.model_config_id ? String(snapshot.model_config_id) : ''
  imageParameters.value = {
    clarity: snapshot.image_parameters.clarity,
    aspectRatio: snapshot.image_parameters.aspect_ratio,
    outputFormat: snapshot.image_parameters.output_format,
    generationCount: snapshot.image_parameters.generation_count,
  }
  selectedLibraryKey.value = snapshot.library_selection.key
  libraryScope.value = snapshot.library_selection.scope
  promptTouched.value = isVariant || snapshot.prompt_touched
  uploadFile.value = null
  if (uploadPreview.value) URL.revokeObjectURL(uploadPreview.value)
  uploadPreview.value = ''
}

function activeFormKey() {
  if (variantDraft.value?.is_new) return 'variant:new'
  return selectedVariant.value ? `variant:${selectedVariant.value.id}` : 'base'
}

function resolveImageFormat(url: string, hint?: string) {
  if (hint) return hint.toUpperCase().replace('JPG', 'JPEG')
  const dataMime = url.match(/^data:image\/([^;,]+)/i)?.[1]
  if (dataMime) return dataMime.toUpperCase().replace('JPG', 'JPEG')
  const extension = url.split(/[?#]/, 1)[0]?.match(/\.([a-z0-9]+)$/i)?.[1]
  return extension?.toUpperCase().replace('JPG', 'JPEG') || 'IMAGE'
}

function recordImageInfo(url: string, event: Event, formatHint?: string) {
  const image = event.currentTarget as HTMLImageElement
  imageInfo.value[url] = {
    dimensions: image.naturalWidth && image.naturalHeight
      ? `${image.naturalWidth} × ${image.naturalHeight}`
      : '',
    format: resolveImageFormat(url, formatHint),
  }
}

function imageInfoLabel(url: string, formatHint?: string) {
  const loaded = imageInfo.value[url]
  return [loaded?.dimensions, loaded?.format || resolveImageFormat(url, formatHint)]
    .filter(Boolean)
    .join(' / ')
}

function openImageLightbox(url: string, alt: string, formatHint?: string) {
  lightboxImage.value = url
  lightboxAlt.value = alt
  lightboxFormat.value = imageInfo.value[url]?.format || resolveImageFormat(url, formatHint)
}

function closeImageLightbox() {
  lightboxImage.value = ''
}

function openAnnotationEditor() {
  if (!props.asset || !generatedImage.value || variantContextActive.value || generationBusy.value) return
  annotationOpen.value = true
}

async function saveAnnotatedImage(blob: Blob) {
  if (!props.asset || annotationSaving.value) return
  annotationSaving.value = true
  try {
    const safeBaseName = (currentImageName.value || 'asset')
      .replace(/[^\p{L}\p{N}_-]+/gu, '-')
      .replace(/^-+|-+$/g, '') || 'asset'
    const file = new File(
      [blob],
      `${safeBaseName}-annotation-${Date.now()}.png`,
      { type: 'image/png' },
    )
    const uploaded = await api.upload(file)
    const imageUrl = `/media/${uploaded.filename}`
    const updated = (await api.recordAssetImageEdit(props.asset.id, {
      image_url: imageUrl,
      source_image_url: generatedImage.value,
      output_format: 'png',
    })).data
    promptSourceAsset.value = updated
    annotationOpen.value = false
    emit('saved', updated)
    await loadGenerationHistory()
    notice.success('标注图已保存，并加入生成记录')
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    annotationSaving.value = false
  }
}

function toggleHistoryError(recordId: string) {
  selectedErrorRecordId.value = selectedErrorRecordId.value === recordId ? '' : recordId
}

function summarizedError(message: string) {
  return isLongError(message) ? `${message.slice(0, 20).trimEnd()}...` : message
}

function isLongError(message: string) {
  return message.length > 48
}

function isCurrentGeneration(record: AssetGenerationRecord) {
  if (selectedVariant.value) return false
  return Boolean(record.images[0] && record.images[0] === generatedImage.value)
}

function selectVariantPreview(variant: AssetVariant | null) {
  formDrafts.set(activeFormKey(), captureFormSnapshot())
  selectedVariant.value = variant
  variantDraft.value = null
  const targetKey = activeFormKey()
  let snapshot = formDrafts.get(targetKey)
  if (!snapshot) {
    const baseSnapshot = formDrafts.get('base') || captureFormSnapshot()
    snapshot = variant ? snapshotForVariant(variant, baseSnapshot) : baseSnapshot
    formDrafts.set(targetKey, snapshot)
  }
  applyFormSnapshot(snapshot, Boolean(variant))
  closeImageLightbox()
}

function updateVariantDraft(draft: AssetVariantDraft | null) {
  variantDraft.value = draft
}

async function restoreGeneration(record: AssetGenerationRecord) {
  if (!props.asset || !record.images[0] || restoringRecordId.value || isCurrentGeneration(record)) return
  restoringRecordId.value = record.id
  try {
    const restored = (await api.restoreAssetGeneration(props.asset.id, record.id)).data
    promptSourceAsset.value = restored
    emit('saved', restored)
    notice.success('已将这次生成结果设为当前图片')
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    restoringRecordId.value = ''
  }
}

function formatHistoryTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

async function loadGenerationHistory() {
  if (!props.asset) {
    generationHistory.value = []
    return
  }
  loadingHistory.value = true
  try {
    generationHistory.value = (await api.assetGenerationHistory(props.asset.id)).data
  } catch (error) {
    notice.error(`生成记录加载失败：${(error as Error).message}`)
  } finally {
    loadingHistory.value = false
  }
}

async function refreshGeneratedResult(assetId: number, variantId?: number) {
  const refreshedAsset = (await api.asset(assetId)).data
  promptSourceAsset.value = refreshedAsset
  emit('saved', refreshedAsset)

  if (variantId) {
    const variants = (await api.assetVariants(assetId)).data
    const refreshedVariant = variants.find(item => item.id === variantId)
    if (refreshedVariant) {
      selectedVariant.value = refreshedVariant
      variantDraft.value = {
        id: refreshedVariant.id,
        name: refreshedVariant.name,
        description: refreshedVariant.description || '',
        chapter_numbers: refreshedVariant.chapter_numbers || [],
        is_new: false,
      }
      variantStripRef.value?.upsertVariant(refreshedVariant)
    }
  }
  await loadGenerationHistory()
}

async function generateAndTrack(assetId: number, variantId?: number) {
  generationController?.abort()
  const controller = new AbortController()
  generationController = controller
  generationRequested.value = true
  generationError.value = ''
  generationTask.value = null

  try {
    const submitted = (await api.generateAsset(assetId, variantId)).data
    if (controller.signal.aborted) return
    generationTask.value = submitted
    saving.value = false
    await loadGenerationHistory()

    const completed = terminalGenerationStatuses.has(submitted.status)
      ? submitted
      : await pollUntilTerminal(async () => {
          const task = (await api.task(submitted.id)).data
          generationTask.value = task
          return task
        }, {
          signal: controller.signal,
          intervalMs: 1500,
          terminalStatuses: terminalGenerationStatuses,
        })

    if (controller.signal.aborted) return
    generationTask.value = completed
    if (completed.status !== TaskStatusEnum.COMPLETED) {
      generationError.value = completed.error_message || (completed.status === TaskStatusEnum.CANCELLED ? '生成任务已取消' : '图片生成失败，请查看生成记录')
      await loadGenerationHistory()
      notice.error(generationError.value)
      return
    }

    await refreshGeneratedResult(assetId, variantId)
    generationRequested.value = false
    notice.success(variantId ? `「${currentImageName.value}」已生成` : `${config.value.label}参考图已生成`)
  } catch (error) {
    if (isAbortError(error)) return
    generationError.value = (error as Error).message || '生成任务提交失败'
    generationTask.value = null
    notice.error(generationError.value)
  } finally {
    if (generationController === controller) generationController = null
  }
}

async function loadReferencePrompt() {
  if (!props.asset || selectedVariant.value || promptTouched.value) return
  try {
    const source = (await api.asset(props.asset.id)).data
    promptSourceAsset.value = source
    const metadata = source.metadata && typeof source.metadata === 'object'
      ? source.metadata as Record<string, unknown>
      : {}
    const characterMetadata = resolveCharacterFormMetadata(source)
    if (!gender.value) gender.value = characterMetadata.gender
    if (!age.value) age.value = characterMetadata.ageGroup
    const preview = await api.referencePromptPreview({
      asset_type: source.asset_type,
      canonical_name: source.canonical_name,
      base_traits: source.base_traits,
      description: source.description,
      metadata: {
        ...metadata,
        reference_layout: referenceLayout.value,
      },
      aspect_ratio: imageParameters.value.aspectRatio,
    })
    if (!promptTouched.value && props.asset?.id === source.id) {
      prompt.value = preview.data.prompt
      promptLanguage.value = preview.data.prompt_language
    }
  } catch (error) {
    notice.error(`提示词预览失败：${(error as Error).message}`)
  }
}

function appendLibraryItems(items: LibraryItem[]) {
  const existing = new Set(libraryItems.value.map(item => item.key))
  libraryItems.value.push(...items.filter(item => !existing.has(item.key)))
}

async function loadPublicPage(page: number) {
  if (props.kind !== 'character') return
  const response = await api.digitalHumans(page)
  publicPage.value = response.data.pagination.page
  publicPages.value = response.data.pagination.pages
  appendLibraryItems(response.data.items.map(item => ({
    key: `public-${item.id}`,
    name: item.occupation || '公共数字人',
    detail: `${item.country} · ${item.gender} · ${item.age} 岁`,
    image: item.image_url,
    source: 'public' as const,
    human: item,
  })))
}

async function loadProjectPage(page: number) {
  const response = await api.assetLibrary(config.value.type, page, 24)
  projectPage.value = response.data.pagination.page
  projectPages.value = response.data.pagination.pages
  appendLibraryItems(response.data.items
    .filter(item => item.novel_id !== props.novelId && item.main_image)
    .map(item => ({
      key: `project-${item.id}`,
      name: item.canonical_name,
      detail: item.description || '其他项目资产',
      image: item.main_image || '',
      source: 'project' as const,
      asset: item,
    })))
}

async function loadSources() {
  loadingLibrary.value = true
  try {
    const configPromise = api.imageGenerationModels()
    await Promise.all([
      props.kind === 'character' ? loadPublicPage(1) : Promise.resolve(),
      loadProjectPage(1),
      loadGenerationHistory(),
    ])
    const configResponse = await configPromise
    models.value = configResponse.data
    if (!models.value.some(item => String(item.config_id) === modelId.value)) {
      modelId.value = String(models.value[0]?.config_id || '')
    }
    await loadReferencePrompt()
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    loadingLibrary.value = false
  }
}

async function loadMoreLibrary() {
  if (loadingLibrary.value || loadingMoreLibrary.value || !libraryHasMore.value) return
  loadingMoreLibrary.value = true
  try {
    const requests: Promise<void>[] = []
    if (libraryScope.value !== 'project' && publicHasMore.value) requests.push(loadPublicPage(publicPage.value + 1))
    if (libraryScope.value !== 'public' && projectHasMore.value) requests.push(loadProjectPage(projectPage.value + 1))
    await Promise.all(requests)
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    loadingMoreLibrary.value = false
  }
}

function onLibraryScroll(event: Event) {
  const target = event.currentTarget as HTMLElement
  if (target.scrollHeight - target.scrollTop - target.clientHeight < 140) void loadMoreLibrary()
}

function acceptFile(file?: File) {
  if (!file) return
  if (!['image/jpeg', 'image/png'].includes(file.type)) {
    notice.info('仅支持 JPG、PNG 格式')
    return
  }
  if (file.size > 20 * 1024 * 1024) {
    notice.info('图片不能超过 20MB')
    return
  }
  uploadFile.value = file
  if (uploadPreview.value) URL.revokeObjectURL(uploadPreview.value)
  uploadPreview.value = URL.createObjectURL(file)
  if (!name.value) name.value = file.name.replace(/\.[^.]+$/, '')
}

function onDrop(event: DragEvent) {
  dragging.value = false
  acceptFile(event.dataTransfer?.files[0])
}

function onWindowKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape' || event.repeat || !props.open) return
  if (annotationOpen.value) return
  event.preventDefault()
  if (lightboxImage.value) {
    closeImageLightbox()
    return
  }
  emit('close')
}

async function submit(regenerate = false) {
  if (!canSubmit.value || saving.value || generationRunning.value) return
  if (regenerate) {
    generationRequested.value = true
    generationError.value = ''
  } else {
    generationRequested.value = false
    generationError.value = ''
  }
  saving.value = true
  try {
    if (props.asset && variantDraft.value) {
      const draft = variantDraft.value
      const variant = selectedVariant.value
      const snapshot = captureFormSnapshot()
      const existingMetadata = asRecord(variant?.metadata)
      const metadata: Record<string, unknown> = {
        ...existingMetadata,
        creation_mode: snapshot.creation_mode,
        clarity: snapshot.image_parameters.clarity,
        aspect_ratio: snapshot.image_parameters.aspect_ratio,
        resolution: snapshot.image_parameters.clarity,
        output_format: snapshot.image_parameters.output_format,
        generation_count: snapshot.image_parameters.generation_count,
        model_config_id: snapshot.model_config_id || undefined,
        gender: snapshot.gender,
        age_group: snapshot.age_group,
        voice: snapshot.voice,
        reference_layout: snapshot.reference_layout,
        [VARIANT_EDITOR_FORM_KEY]: snapshot,
      }
      let images = variant?.images || []
      if (snapshot.creation_mode === 'upload' && uploadFile.value) {
        const uploaded = await api.upload(uploadFile.value)
        images = [`/media/${uploaded.filename}`, ...images.filter(Boolean)]
      } else if (snapshot.creation_mode === 'library' && selectedLibrary.value?.image) {
        images = [selectedLibrary.value.image, ...images.filter(image => image !== selectedLibrary.value?.image)]
        metadata.library_source = selectedLibrary.value.source
        metadata.source_asset_id = selectedLibrary.value.asset?.id || selectedLibrary.value.human?.asset_id
      }
      const variantPayload: Partial<AssetVariant> & { name: string } = {
        name: draft.name.trim(),
        description: draft.description || undefined,
        chapter_numbers: draft.chapter_numbers,
        base_traits: snapshot.base_traits,
        images,
        metadata,
      }
      const updated = variant
        ? (await api.updateAssetVariant(props.asset.id, variant.id, variantPayload)).data
        : (await api.createAssetVariant(props.asset.id, variantPayload)).data
      selectedVariant.value = updated
      variantDraft.value = {
        id: updated.id,
        name: updated.name,
        description: updated.description || '',
        chapter_numbers: updated.chapter_numbers || [],
        is_new: false,
      }
      variantStripRef.value?.upsertVariant(updated)
      formDrafts.set(`variant:${updated.id}`, snapshot)
      if (regenerate) {
        await generateAndTrack(props.asset.id, updated.id)
        return
      }
      notice.success(`「${updated.name}」版本已保存`)
      emit('close')
      return
    }

    let assetName = name.value.trim()
    let assetDescription = description.value.trim()
    let mainImage: string | undefined
    let imageSource = 1
    const existingMetadata = props.asset?.metadata && typeof props.asset.metadata === 'object'
      ? props.asset.metadata as Record<string, unknown>
      : {}
    const metadata: Record<string, unknown> = {
      ...existingMetadata,
      creation_mode: mode.value,
      clarity: imageParameters.value.clarity,
      aspect_ratio: imageParameters.value.aspectRatio,
      resolution: imageParameters.value.clarity,
      output_format: imageParameters.value.outputFormat,
      generation_count: 1,
      model_config_id: Number(modelId.value) || undefined,
    }

    if (props.kind === 'character') {
      Object.assign(metadata, {
        gender: isGroupPortrait.value ? '' : gender.value,
        age_group: isGroupPortrait.value ? '' : age.value,
        voice: isGroupPortrait.value ? '' : voice.value,
        reference_layout: referenceLayout.value,
      })
    }

    if (mode.value === 'upload' && uploadFile.value) {
      const uploaded = await api.upload(uploadFile.value)
      mainImage = `/media/${uploaded.filename}`
      imageSource = 2
    }

    if (mode.value === 'library' && selectedLibrary.value) {
      const selected = selectedLibrary.value
      assetName = selected.name
      assetDescription = selected.asset?.description || selected.detail
      mainImage = selected.image
      imageSource = 2
      metadata.library_source = selected.source
      metadata.source_asset_id = selected.asset?.id || selected.human?.asset_id
      if (selected.human) Object.assign(metadata, { gender: selected.human.gender, age: selected.human.age, country: selected.human.country, occupation: selected.human.occupation })
    }

    const payload: Partial<Asset> = {
      asset_type: config.value.type,
      canonical_name: assetName,
      description: assetDescription,
      base_traits: promptTouched.value
        ? prompt.value.trim()
        : promptSourceAsset.value?.base_traits || prompt.value.trim(),
      main_image: mainImage,
      image_source: imageSource,
      metadata,
      is_global: false,
    }
    const response = props.asset
      ? await api.updateAsset(props.asset.id, payload)
      : await api.createAsset({ ...payload, novel_id: props.novelId } as Partial<Asset> & { novel_id: number; asset_type: number; canonical_name: string })

    if (props.asset) {
      promptSourceAsset.value = response.data
      emit('saved', response.data)
      if (regenerate) {
        await generateAndTrack(response.data.id)
        return
      }
      notice.success(`${config.value.label}已更新`)
    } else if (mode.value === 'ai') {
      await api.generateAsset(response.data.id)
      notice.success(`${config.value.label}已创建，正在生成参考图`)
      emit('created', response.data)
    } else {
      notice.success(`${config.value.label}已添加`)
      emit('created', response.data)
    }
    emit('close')
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    saving.value = false
  }
}

watch(() => props.open, value => {
  if (!value) {
    generationController?.abort()
    generationController = null
    closeImageLightbox()
    annotationOpen.value = false
    document.body.style.overflow = previousBodyOverflow
    return
  }
  previousBodyOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  reset()
  void loadSources()
})
watch(() => props.kind, () => { if (props.open) { reset(); void loadSources() } })
watch(() => props.asset?.id, () => { if (props.open) reset() })
watch(() => props.asset?.main_image, () => {
  if (!props.open || !props.asset) return
  promptSourceAsset.value = props.asset
  void loadGenerationHistory()
})
watch([referenceLayout, () => imageParameters.value.aspectRatio], () => {
  if (props.open && props.asset && !promptTouched.value) void loadReferencePrompt()
})
watch(selectedModel, model => {
  if (!model) return
  const current = imageParameters.value
  const capabilities = model.capabilities
  imageParameters.value = {
    clarity: capabilities.clarities.includes(current.clarity) ? current.clarity : capabilities.default_clarity,
    aspectRatio: capabilities.aspect_ratios.includes(current.aspectRatio) ? current.aspectRatio : capabilities.default_aspect_ratio,
    outputFormat: capabilities.output_formats.includes(current.outputFormat) ? current.outputFormat : capabilities.default_output_format,
    generationCount: capabilities.generation_counts.includes(current.generationCount) ? current.generationCount : capabilities.default_generation_count,
  }
}, { immediate: true })
onMounted(() => {
  window.addEventListener('keydown', onWindowKeydown)
  if (props.open) {
    previousBodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    reset()
    void loadSources()
  }
})
onUnmounted(() => {
  generationController?.abort()
  window.removeEventListener('keydown', onWindowKeydown)
  document.body.style.overflow = previousBodyOverflow
})
</script>

<template>
  <Teleport to="body">
    <Transition name="asset-backdrop">
      <div v-if="open" class="asset-dialog-backdrop" aria-hidden="true" @click="emit('close')" />
    </Transition>
    <Transition name="asset-drawer">
      <form v-if="open" class="asset-dialog" role="dialog" aria-modal="true" aria-labelledby="asset-dialog-title" @submit.prevent="submit(false)">
        <header class="asset-dialog__header">
          <span class="asset-dialog__icon"><component :is="config.icon" :size="18" /></span>
          <div><span>PROJECT ASSET</span><h2 id="asset-dialog-title">{{ isEditing ? '编辑' : '新增' }}{{ config.label }}</h2></div>
          <AppButton type="button" variant="ghost" size="sm" icon-only aria-label="关闭" @click="emit('close')"><X :size="18" /></AppButton>
        </header>

        <div class="asset-dialog__body">
          <section v-if="isEditing || generatedImage" class="asset-generated-preview" aria-label="当前图片">
            <header>
              <strong>当前图片 · {{ currentImageName }}</strong>
              <span v-if="generationBusy || generationError" class="asset-generated-preview__status" :class="{ 'is-error': generationError }">
                <i aria-hidden="true" />{{ generationStatusText }}
              </span>
              <span v-else>{{ generatedImage ? imageInfoLabel(generatedImage, currentImageFormat) : '尚未生成' }}</span>
            </header>
            <div v-if="generatedImage" class="asset-generated-preview__canvas">
              <button type="button" class="asset-generated-preview__viewer" :class="{ 'is-generating': generationBusy }" aria-label="放大查看当前图片" @click="openImageLightbox(generatedImage, `${currentImageName}的生成图片`, currentImageFormat)">
                <img :src="generatedImage" :alt="`${currentImageName}的生成图片`" @load="recordImageInfo(generatedImage, $event, currentImageFormat)" />
                <span class="asset-generated-preview__zoom"><Maximize2 :size="15" />放大查看</span>
                <span v-if="generationBusy" class="asset-generated-preview__overlay" aria-hidden="true">
                  <i><LoaderCircle :size="25" /></i>
                </span>
              </button>
              <AppButton
                v-if="props.asset && !variantContextActive && !generationBusy"
                type="button"
                variant="secondary"
                size="sm"
                icon-only
                class="asset-generated-preview__edit"
                aria-label="编辑当前图片标注"
                title="编辑图片"
                @click="openAnnotationEditor"
              ><Pencil :size="15" /></AppButton>
            </div>
            <div v-else-if="generationBusy" class="asset-generated-preview__generating" role="status" aria-live="polite">
              <span class="asset-generated-preview__loader"><LoaderCircle :size="30" /></span>
              <strong>{{ generationStatusText }}</strong>
              <span>{{ generationStatusMessage }}</span>
            </div>
            <div v-else class="asset-generated-preview__empty" role="status"><ImagePlus :size="30" /><strong>暂无图片</strong><span>可以上传或生成该衍生形象</span></div>
            <Transition name="asset-generation-status">
              <div v-if="(generationBusy && generatedImage) || generationError" class="asset-generation-status" :class="{ 'is-error': generationError }" role="status" aria-live="polite">
                <span><LoaderCircle v-if="!generationError" :size="17" /><CircleAlert v-else :size="17" /></span>
                <div><strong>{{ generationStatusText }}</strong><small>{{ generationStatusMessage }}</small></div>
              </div>
            </Transition>
          </section>

          <section v-if="isEditing" class="asset-generation-history" aria-labelledby="asset-history-title">
            <header>
              <div><Clock3 :size="15" /><strong id="asset-history-title">生成记录</strong><span>{{ generationHistory.length }} 次</span></div>
              <AppButton type="button" variant="ghost" size="xs" icon-only aria-label="刷新生成记录" title="刷新生成记录" :loading="loadingHistory" @click="loadGenerationHistory"><RefreshCw v-if="!loadingHistory" :size="14" /></AppButton>
            </header>
            <div v-if="loadingHistory && !generationHistory.length" class="asset-generation-history__state">正在加载生成记录…</div>
            <div v-else-if="!generationHistory.length" class="asset-generation-history__state">还没有生成记录</div>
            <div v-else class="asset-generation-history__list">
              <article v-for="record in generationHistory" :key="record.id" :class="`is-status-${record.status}`">
                <button v-if="record.images[0]" type="button" class="asset-generation-history__image" :aria-label="`放大查看${formatHistoryTime(record.created_at)}的生成图片`" @click="openImageLightbox(record.images[0], `${name}的历史生成图片`, record.output_format)">
                  <img :src="record.images[0]" :alt="`${name}的历史生成图片`" loading="lazy" @load="recordImageInfo(record.images[0], $event, record.output_format)" />
                  <span>{{ imageInfoLabel(record.images[0], record.output_format) }}</span>
                </button>
                <span v-else class="asset-generation-history__placeholder"><LoaderCircle v-if="record.status === TaskStatusEnum.PROCESSING || record.status === TaskStatusEnum.PENDING || record.status === TaskStatusEnum.QUEUED" :size="18" /><ImagePlus v-else :size="18" /></span>
                <div>
                  <strong>{{ historyStatus(record.status) }}</strong>
                  <small>{{ formatHistoryTime(record.created_at) }}</small>
                  <p>{{ [record.model, record.aspect_ratio, record.clarity, record.output_format?.toUpperCase()].filter(Boolean).join(' / ') || '使用当前模型配置' }}</p>
                  <div v-if="record.error_message" class="asset-generation-history__error">
                    <span>{{ summarizedError(record.error_message) }}</span>
                    <button
                      v-if="isLongError(record.error_message)"
                      type="button"
                      :aria-expanded="selectedErrorRecordId === record.id"
                      :aria-label="`查看${formatHistoryTime(record.created_at)}的失败详情`"
                      @click="toggleHistoryError(record.id)"
                    >
                      查看详情<ChevronDown :size="12" />
                    </button>
                  </div>
                  <AppButton
                    v-if="record.status === TaskStatusEnum.COMPLETED && record.images[0]"
                    type="button"
                    class="asset-generation-history__restore"
                    variant="ghost"
                    size="xs"
                    :disabled="isCurrentGeneration(record) || Boolean(restoringRecordId)"
                    :loading="restoringRecordId === record.id"
                    @click="restoreGeneration(record)"
                  >
                    <Check v-if="isCurrentGeneration(record)" :size="12" />
                    <Undo2 v-else-if="restoringRecordId !== record.id" :size="12" />
                    {{ isCurrentGeneration(record) ? '当前使用' : '设为当前' }}
                  </AppButton>
                </div>
              </article>
            </div>
            <Transition name="asset-error-detail">
              <section v-if="selectedErrorRecord?.error_message" class="asset-generation-error-detail" role="region" aria-label="生成失败详情">
                <header>
                  <div>
                    <strong>失败详情</strong>
                    <span>{{ formatHistoryTime(selectedErrorRecord.created_at) }}</span>
                  </div>
                  <AppButton type="button" variant="ghost" size="xs" icon-only aria-label="关闭失败详情" @click="selectedErrorRecordId = ''"><X :size="13" /></AppButton>
                </header>
                <small>{{ [selectedErrorRecord.model, selectedErrorRecord.aspect_ratio, selectedErrorRecord.clarity, selectedErrorRecord.output_format?.toUpperCase()].filter(Boolean).join(' / ') || '使用当前模型配置' }}</small>
                <pre>{{ selectedErrorRecord.error_message }}</pre>
              </section>
            </Transition>
          </section>

          <AssetVariantStrip
            v-if="isEditing && asset"
            ref="variantStripRef"
            :asset="asset"
            :chapter-number="chapterNumber"
            :episode-numbers="episodeNumbers"
            @select="selectVariantPreview"
            @draft="updateVariantDraft"
          />

          <div class="asset-form-grid" :class="{ 'is-character': kind === 'character' && !isGroupPortrait }">
            <label class="asset-field"><span><i>*</i>名称</span><input v-model="name" maxlength="100" placeholder="请输入" /></label>
            <label v-if="kind === 'character' && !isGroupPortrait" class="asset-field"><span><i>*</i>性别</span><AppSelect v-model="gender" :options="genderOptions" ariaLabel="选择性别" menu-label="性别" /></label>
            <label v-if="kind === 'character' && !isGroupPortrait" class="asset-field"><span><i>*</i>年龄</span><AppSelect v-model="age" :options="ageOptions" ariaLabel="选择年龄阶段" menu-label="年龄" /></label>
            <label v-if="kind === 'character' && !isGroupPortrait" class="asset-field"><span>音色选择</span><AppButton type="button" variant="secondary" block @click="notice.info('音频库将在下一步开放选择')"><Volume2 :size="15" />{{ voice || '选择音色' }}</AppButton></label>
          </div>

          <fieldset class="asset-mode">
            <legend><i>*</i>形象生成方式</legend>
            <div>
              <AppButton type="button" variant="ghost" :active="mode === 'ai'" @click="mode = 'ai'"><Sparkles :size="15" />AI 生成</AppButton>
              <AppButton type="button" variant="ghost" :active="mode === 'library'" @click="mode = 'library'"><Library :size="15" />从{{ config.library }}选择</AppButton>
              <AppButton type="button" variant="ghost" :active="mode === 'upload'" @click="mode = 'upload'"><Upload :size="15" />本地上传</AppButton>
            </div>
          </fieldset>

          <template v-if="mode === 'ai'">
            <label v-if="kind === 'character'" class="asset-field"><span>参考图版式</span><AppSelect v-model="referenceLayout" :options="referenceLayoutOptions" ariaLabel="选择人物参考图版式" menu-label="参考图版式" /></label>
            <label class="asset-field">
              <span><i>*</i>提示词<small v-if="isEditing">最终发送 · {{ promptLanguage === 'zh' ? '中文' : 'English' }}</small></span>
              <textarea v-model="prompt" rows="8" :placeholder="promptPlaceholder" @input="promptTouched = true" />
            </label>
          </template>

          <section v-else-if="mode === 'library'" class="asset-library">
            <header>
              <label><Search :size="16" /><input v-model="search" type="search" :placeholder="`搜索${config.library}`" /></label>
              <nav v-if="kind === 'character'">
                <AppButton v-for="item in [{ value: 'all', label: '全部' }, { value: 'public', label: '公共数字人' }, { value: 'project', label: '项目人物' }]" :key="item.value" type="button" variant="soft" size="sm" :active="libraryScope === item.value" @click="libraryScope = item.value as 'all' | 'public' | 'project'">{{ item.label }}</AppButton>
              </nav>
            </header>
            <div class="asset-library__grid" @scroll.passive="onLibraryScroll">
              <div v-if="loadingLibrary" class="asset-library__state">正在加载资产库…</div>
              <AppButton v-for="item in filteredLibraryItems" v-else :key="item.key" type="button" class="asset-library__card" :active="selectedLibraryKey === item.key" @click="selectedLibraryKey = item.key">
                <img :src="item.image" alt="" loading="lazy" />
                <span><strong>{{ item.name }}</strong><small>{{ item.detail }}</small></span>
                <Check v-if="selectedLibraryKey === item.key" :size="16" />
              </AppButton>
              <div v-if="!loadingLibrary && !filteredLibraryItems.length" class="asset-library__state">暂无可用{{ config.label }}资产</div>
              <div v-if="!loadingLibrary && filteredLibraryItems.length" class="asset-library__paging" role="status" aria-live="polite">
                <template v-if="loadingMoreLibrary"><LoaderCircle :size="15" />正在加载下一页…</template>
                <template v-else-if="libraryHasMore">继续下滑加载更多</template>
                <template v-else>已加载全部</template>
              </div>
            </div>
          </section>

          <label v-else class="asset-upload" :class="{ 'is-dragging': dragging, 'has-file': uploadPreview }" @dragenter.prevent="dragging = true" @dragover.prevent @dragleave.prevent="dragging = false" @drop.prevent="onDrop">
            <input type="file" accept="image/jpeg,image/png" @change="acceptFile(($event.target as HTMLInputElement).files?.[0])" />
            <img v-if="uploadPreview" :src="uploadPreview" alt="上传预览" />
            <template v-else><Upload :size="26" /><strong>点击或拖拽图片到此处上传</strong><span>仅支持 JPG、PNG，最大 20MB</span></template>
          </label>

          <label class="asset-field"><span>{{ config.label }}描述</span><textarea v-model="description" rows="3" placeholder="请输入" /></label>
        </div>

        <footer class="asset-dialog__footer">
          <div v-if="mode === 'ai'" class="asset-generation-options">
            <AppSelect v-model="modelId" :options="modelOptions" ariaLabel="选择生图模型"><template #leading><Sparkles :size="14" /></template></AppSelect>
            <ImageGenerationParameterPanel v-model="imageParameters" :capabilities="selectedModel?.capabilities" />
          </div>
          <span v-else />
          <div>
            <AppButton type="button" variant="secondary" @click="emit('close')">取消</AppButton>
            <AppButton v-if="isEditing && mode === 'ai'" type="button" variant="secondary" :disabled="!canSubmit || generationBusy" :loading="generationBusy" @click="submit(true)"><RefreshCw v-if="!generationBusy" :size="15" />{{ generationBusy ? generationStatusText : variantDraft?.is_new ? '生成' : '重新生成' }}</AppButton>
            <AppButton type="submit" variant="primary" :disabled="!canSubmit || generationBusy" :loading="saving && !generationRequested"><Sparkles v-if="!isEditing && !saving && mode === 'ai'" :size="15" />{{ variantContextActive ? mode === 'upload' ? '上传并保存' : mode === 'library' ? '选择并保存' : '保存此版本' : isEditing ? '保存修改' : mode === 'ai' ? '开始生成' : '确认添加' }}</AppButton>
          </div>
        </footer>
      </form>
    </Transition>
  </Teleport>
  <ImageLightbox :open="Boolean(lightboxImage)" :src="lightboxImage" :alt="lightboxAlt" :format="lightboxFormat" @close="closeImageLightbox" />
  <ImageAnnotationEditor
    :open="annotationOpen"
    :image-url="generatedImage"
    :title="currentImageName"
    :saving="annotationSaving"
    @close="annotationOpen = false"
    @save="saveAnnotatedImage"
  />
</template>

<style scoped>
.asset-dialog-backdrop { position: fixed; inset: 0; z-index: 120; background: rgb(35 38 52 / 42%); backdrop-filter: blur(6px); }
.asset-dialog { position: fixed; top: 0; right: 0; bottom: 0; z-index: 121; display: flex; width: min(760px,calc(100vw - 24px)); height: 100dvh; flex-direction: column; overflow: hidden; border: 0; border-radius: 24px 0 0 24px; background: #fff; box-shadow: -28px 0 90px rgb(25 28 45 / 24%); }
.asset-backdrop-enter-active,.asset-backdrop-leave-active { transition: opacity .22s ease; }
.asset-backdrop-enter-from,.asset-backdrop-leave-to { opacity: 0; }
.asset-drawer-enter-active,.asset-drawer-leave-active { transition: transform .28s cubic-bezier(.2,.72,.2,1),box-shadow .28s ease; }
.asset-drawer-enter-from,.asset-drawer-leave-to { box-shadow: none; transform: translateX(100%); }
.asset-dialog__header { display: grid; grid-template-columns: 36px 1fr 32px; align-items: center; gap: 10px; padding: 11px 18px; background: linear-gradient(135deg,#fbfbff,#f4f5ff); }
.asset-dialog__icon { display: grid; width: 36px; height: 36px; place-items: center; border-radius: 11px; color: #5b5df0; background: #fff; box-shadow: 0 6px 16px rgb(73 75 159 / 9%); }
.asset-dialog__header > div > span { color: #7779ef; font-size: 8px; font-weight: 800; letter-spacing: .13em; }
.asset-dialog__header h2 { margin: 0; color: #292d3a; font-size: 17px; line-height: 1.2; }
.asset-dialog__body { display: grid; min-width: 0; gap: 17px; overflow-x: hidden; overflow-y: auto; padding: 18px 22px 20px; }
.asset-generated-preview { display: grid; gap: 8px; }
.asset-generated-preview > header { display: flex; align-items: center; justify-content: space-between; color: #535968; font-size: 12px; }
.asset-generated-preview > header strong { font-weight: 650; }
.asset-generated-preview > header span { color: #858c9b; font-size: 10px; font-variant-numeric: tabular-nums; }
.asset-generated-preview > header .asset-generated-preview__status { display: inline-flex; align-items: center; gap: 6px; color: #5d5ff0; font-weight: 700; }
.asset-generated-preview__status i { width: 6px; height: 6px; border-radius: 999px; background: currentColor; box-shadow: 0 0 0 0 rgb(93 95 240 / 28%); animation: asset-generation-pulse 1.45s ease-out infinite; }
.asset-generated-preview > header .asset-generated-preview__status.is-error { color: #ca4052; }
.asset-generated-preview__status.is-error i { box-shadow: none; animation: none; }
.asset-generated-preview__canvas { position: relative; min-width: 0; }
.asset-generated-preview__viewer { position: relative; display: grid; width: 100%; min-height: 220px; max-height: min(520px,52vh); place-items: center; overflow: hidden; padding: 0; border: 0; border-radius: 16px; outline: 0; background: #f7f8fa; cursor: zoom-in; }
.asset-generated-preview__viewer img { display: block; width: auto; max-width: 100%; height: auto; max-height: min(520px,52vh); object-fit: contain; transition: transform .24s cubic-bezier(.2,.72,.2,1); }
.asset-generated-preview__viewer > .asset-generated-preview__zoom { position: absolute; right: 12px; bottom: 12px; display: flex; align-items: center; gap: 6px; padding: 7px 9px; border-radius: 9px; color: #fff; background: rgb(43 46 55 / 74%); font-size: 10px; opacity: 0; transform: translateY(5px); transition: opacity .18s ease,transform .2s ease; backdrop-filter: blur(8px); }
.asset-generated-preview__viewer.is-generating { cursor: progress; }
.asset-generated-preview__viewer.is-generating::after { position: absolute; inset: 0; background: linear-gradient(105deg,transparent 30%,rgb(255 255 255 / 38%) 48%,transparent 66%); content: ''; transform: translateX(-100%); animation: asset-generation-shimmer 1.8s ease-in-out infinite; pointer-events: none; }
.asset-generated-preview__overlay { position: absolute; inset: 0; z-index: 1; display: grid; place-items: center; background: rgb(246 247 252 / 24%); pointer-events: none; }
.asset-generated-preview__overlay > i { display: grid; width: 50px; height: 50px; place-items: center; border: 1px solid rgb(255 255 255 / 72%); border-radius: 16px; color: #5d5ff0; background: rgb(255 255 255 / 82%); box-shadow: 0 10px 30px rgb(49 51 96 / 14%); font-style: normal; backdrop-filter: blur(10px); }
.asset-generated-preview__overlay svg { animation: asset-library-spin .8s linear infinite; }
.asset-generated-preview__viewer:hover img { transform: scale(1.012); }
.asset-generated-preview__viewer:hover > .asset-generated-preview__zoom,.asset-generated-preview__viewer:focus-visible > .asset-generated-preview__zoom { opacity: 1; transform: translateY(0); }
.asset-generated-preview__viewer:focus-visible { box-shadow: 0 0 0 3px rgb(91 93 240 / 18%); }
.asset-generated-preview__edit { position: absolute; z-index: 3; top: 12px; right: 12px; opacity: 0; transform: translateY(-4px); transition: opacity .18s ease,transform .2s cubic-bezier(.2,.72,.2,1); }
.asset-generated-preview__canvas:hover .asset-generated-preview__edit,.asset-generated-preview__edit:focus-visible { opacity: 1; transform: translateY(0); }
.asset-generated-preview__empty { display: grid; min-height: 220px; place-items: center; align-content: center; gap: 6px; border-radius: 16px; color: var(--app-text-muted); background: var(--app-surface-muted); }
.asset-generated-preview__empty strong { color: var(--app-text-secondary); font-size: 12px; }
.asset-generated-preview__empty span { font-size: 9px; }
.asset-generated-preview__generating { position: relative; display: grid; min-height: 220px; place-items: center; align-content: center; gap: 8px; overflow: hidden; border-radius: 16px; color: var(--app-text-muted); background: color-mix(in srgb,var(--app-accent-soft) 45%,var(--app-surface-muted)); }
.asset-generated-preview__generating::before { position: absolute; inset: 0; background: linear-gradient(105deg,transparent 28%,rgb(255 255 255 / 60%) 48%,transparent 68%); content: ''; transform: translateX(-100%); animation: asset-generation-shimmer 1.8s ease-in-out infinite; }
.asset-generated-preview__generating > * { position: relative; z-index: 1; }
.asset-generated-preview__generating strong { color: var(--app-accent); font-size: 12px; }
.asset-generated-preview__generating > span:last-child { font-size: 9px; }
.asset-generated-preview__loader { display: grid; width: 52px; height: 52px; place-items: center; border: 1px solid color-mix(in srgb,var(--app-accent) 14%,var(--app-border)); border-radius: 16px; color: var(--app-accent); background: var(--app-surface-raised); box-shadow: var(--app-shadow); }
.asset-generated-preview__loader svg { animation: asset-library-spin .8s linear infinite; }
.asset-generation-status { display: grid; min-width: 0; grid-template-columns: 32px minmax(0,1fr); align-items: center; gap: 9px; padding: 9px 10px; border-radius: 11px; color: #5557e7; background: #f2f2ff; }
.asset-generation-status > span { display: grid; width: 32px; height: 32px; place-items: center; border-radius: 9px; background: #fff; }
.asset-generation-status svg { animation: asset-library-spin .8s linear infinite; }
.asset-generation-status div { display: grid; min-width: 0; gap: 2px; }
.asset-generation-status strong { font-size: 10px; }
.asset-generation-status small { overflow: hidden; color: #777d8d; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.asset-generation-status.is-error { color: #c5384c; background: #fff1f2; }
.asset-generation-status.is-error > span { background: #fff; }
.asset-generation-status.is-error svg { animation: none; }
.asset-generation-status-enter-active,.asset-generation-status-leave-active { transition: opacity .18s ease,transform .2s cubic-bezier(.2,.72,.2,1); }
.asset-generation-status-enter-from,.asset-generation-status-leave-to { opacity: 0; transform: translateY(-5px); }
.asset-generation-history { display: grid; gap: 10px; padding-top: 4px; }
.asset-generation-history > header,.asset-generation-history > header > div { display: flex; align-items: center; gap: 7px; }
.asset-generation-history > header { justify-content: space-between; color: #656b7a; }
.asset-generation-history > header strong { color: #424755; font-size: 12px; }
.asset-generation-history > header span { font-size: 10px; }
.asset-generation-history__state { display: grid; min-height: 72px; place-items: center; color: #979dab; font-size: 11px; }
.asset-generation-history__list { display: grid; min-width: 0; max-height: 250px; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 6px 14px; overflow-x: hidden; overflow-y: auto; padding-right: 2px; }
.asset-generation-history__list article { display: grid; min-width: 0; grid-template-columns: 82px minmax(0,1fr); gap: 10px; padding: 7px 0; border-radius: 10px; transition: background .16s ease; }
.asset-generation-history__list article:hover { background: #f8f9fb; }
.asset-generation-history__image { position: relative; display: block; width: 82px; height: 72px; overflow: hidden; padding: 0; border: 0; border-radius: 10px; outline: 0; background: #f0f1f4; cursor: zoom-in; }
.asset-generation-history__image img { display: block; width: 100%; height: 100%; object-fit: cover; transition: transform .2s cubic-bezier(.2,.72,.2,1); }
.asset-generation-history__image span { position: absolute; right: 0; bottom: 0; left: 0; overflow: hidden; padding: 10px 5px 4px; color: #fff; background: linear-gradient(transparent,rgb(36 39 47 / 78%)); font-size: 8px; font-variant-numeric: tabular-nums; text-overflow: ellipsis; white-space: nowrap; }
.asset-generation-history__image:hover img { transform: scale(1.04); }
.asset-generation-history__image:focus-visible { box-shadow: 0 0 0 3px rgb(91 93 240 / 20%); }
.asset-generation-history__placeholder { width: 82px; height: 72px; border-radius: 10px; background: #f0f1f4; }
.asset-generation-history__placeholder { display: grid; place-items: center; color: #a0a6b4; }
.asset-generation-history__list article.is-status-1 .asset-generation-history__placeholder svg,.asset-generation-history__list article.is-status-2 .asset-generation-history__placeholder svg,.asset-generation-history__list article.is-status-6 .asset-generation-history__placeholder svg { color: #6668f6; animation: asset-library-spin .8s linear infinite; }
.asset-generation-history__list article > div { display: grid; min-width: 0; overflow: hidden; align-content: center; grid-template-columns: minmax(0,1fr) auto; gap: 3px 6px; }
.asset-generation-history__list strong { color: #4e5462; font-size: 10px; }
.asset-generation-history__list small { color: #a0a5b2; font-size: 9px; }
.asset-generation-history__list p { grid-column: 1/-1; overflow: hidden; margin: 0; font-size: 9px; line-height: 1.35; text-overflow: ellipsis; white-space: nowrap; }
.asset-generation-history__list p { color: #8d93a1; }
.asset-generation-history__list article .asset-generation-history__error { display: flex !important; min-width: 0; overflow: hidden; grid-column: 1/-1; align-items: center; gap: 5px; color: #c92f43; font-size: 8px; line-height: 1.3; }
.asset-generation-history__list article .asset-generation-history__error > span { min-width: 0; overflow: hidden; flex: 1; color: #c92f43; font-size: 8px; font-weight: 550; text-overflow: ellipsis; white-space: nowrap; }
.asset-generation-history__list article .asset-generation-history__error > button { display: inline-flex; flex: 0 0 auto; align-items: center; gap: 1px; padding: 0; border: 0; color: #c92f43; background: transparent; font-family: inherit; font-size: 8px; font-weight: 700; line-height: 1.3; cursor: pointer; }
.asset-generation-history__list article .asset-generation-history__error > button:hover,.asset-generation-history__list article .asset-generation-history__error > button:focus-visible { color: #a91f32; text-decoration: underline; text-underline-offset: 2px; }
.asset-generation-history__error > button svg { transition: transform .16s ease; }
.asset-generation-history__error > button[aria-expanded="true"] svg { transform: rotate(180deg); }
.asset-generation-error-detail { display: grid; min-width: 0; gap: 7px; padding: 11px 12px; border-radius: 11px; color: var(--app-text-secondary); background: var(--app-surface-muted); }
.asset-generation-error-detail > header,.asset-generation-error-detail > header > div { display: flex; align-items: center; gap: 7px; }
.asset-generation-error-detail > header { justify-content: space-between; }
.asset-generation-error-detail > header strong { color: var(--app-text); font-size: 11px; }
.asset-generation-error-detail > header span,.asset-generation-error-detail > small { color: var(--app-text-muted); font-size: 9px; }
.asset-generation-error-detail pre { max-width: 100%; max-height: 150px; overflow-x: hidden; overflow-y: auto; margin: 0; color: #b84958; font-family: inherit; font-size: 10px; font-weight: 500; line-height: 1.55; overflow-wrap: anywhere; white-space: pre-wrap; word-break: break-word; }
.asset-error-detail-enter-active,.asset-error-detail-leave-active { transition: opacity .16s ease,transform .18s ease; }
.asset-error-detail-enter-from,.asset-error-detail-leave-to { opacity: 0; transform: translateY(-4px); }
.asset-generation-history__restore { min-height: 24px; grid-column: 1/-1; justify-self: start; padding: 0 4px; color: #6466e8; font-size: 9px; }
.asset-form-grid { display: grid; grid-template-columns: 1fr; gap: 14px; }
.asset-form-grid.is-character { grid-template-columns: 1fr 1fr; }
.asset-field { display: grid; gap: 7px; color: #535968; font-size: 12px; font-weight: 650; }
.asset-field > span { display: flex; align-items: center; gap: 6px; }
.asset-field > span small { margin-left: auto; color: var(--app-text-muted); font-size: 9px; font-weight: 500; }
.asset-field > span i,.asset-mode legend i { margin-right: 3px; color: #ec5e73; font-style: normal; }
.asset-field input,.asset-field textarea { width: 100%; padding: 10px 12px; border: 0; border-radius: 11px; outline: 0; color: #343847; background: #f6f7fa; font: inherit; font-weight: 450; box-shadow: inset 0 0 0 1px transparent; transition: .16s ease; resize: vertical; }
.asset-field input { height: 40px; }
.asset-field input:focus,.asset-field textarea:focus { background: #fff; box-shadow: inset 0 0 0 1px #8587f7,0 0 0 3px rgb(91 93 240 / 9%); }
.asset-field :deep(.app-select__trigger) { min-height: 40px; border: 0; background: #f6f7fa; box-shadow: none; }
.asset-mode { min-width: 0; margin: 0; padding: 0; border: 0; }
.asset-mode legend { margin-bottom: 7px; color: #535968; font-size: 12px; font-weight: 650; }
.asset-mode > div { display: grid; grid-template-columns: repeat(3,1fr); gap: 5px; padding: 4px; border-radius: 13px; background: #f3f4f8; }
.asset-mode :deep(.app-button) { min-height: 38px; color: #646a7a; }
.asset-mode :deep(.app-button.is-active) { color: #5658eb; background: #fff; box-shadow: 0 5px 18px rgb(47 50 80 / 8%); }
.asset-upload { position: relative; display: grid; min-height: 250px; place-items: center; align-content: center; gap: 8px; overflow: hidden; border-radius: 17px; color: #9399a8; background: #fafbfe; box-shadow: inset 0 0 0 1.5px #dde1ef; cursor: pointer; transition: .18s ease; }
.asset-upload:hover,.asset-upload.is-dragging { color: #6567ef; background: #f7f7ff; box-shadow: inset 0 0 0 1.5px #a8a9fa; }
.asset-upload input { position: absolute; inset: 0; width: 100%; height: 100%; color: transparent; opacity: 0; cursor: pointer; font-size: 0; }
.asset-upload input::file-selector-button { display: none; }
.asset-upload strong { color: #515766; font-size: 13px; }
.asset-upload span { font-size: 11px; }
.asset-upload img { width: 100%; height: 300px; object-fit: contain; background: #f2f3f7; }
.asset-library { overflow: hidden; border-radius: 16px; background: #f8f9fc; }
.asset-library > header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 11px; }
.asset-library > header label { display: flex; min-height: 38px; flex: 1; align-items: center; gap: 8px; padding: 0 11px; border-radius: 10px; color: #9298a7; background: #fff; }
.asset-library > header input { min-width: 0; flex: 1; border: 0; outline: 0; background: transparent; font: inherit; }
.asset-library nav { display: flex; gap: 4px; }
.asset-library__grid { display: grid; max-height: 320px; grid-template-columns: repeat(3,1fr); gap: 10px; overflow-y: auto; padding: 0 11px 11px; }
.asset-library__card { position: relative; display: grid; height: auto; min-height: 0; grid-template-columns: 64px 1fr; gap: 9px; justify-content: stretch; overflow: hidden; padding: 7px; border-radius: 13px; text-align: left; background: #fff; box-shadow: 0 4px 14px rgb(38 42 62 / 5%); }
.asset-library__card.is-active { color: #4f51e6; box-shadow: inset 0 0 0 2px #7779f4,0 8px 20px rgb(73 75 190 / 12%); }
.asset-library__card img { width: 64px; height: 72px; border-radius: 9px; object-fit: cover; }
.asset-library__card > span { display: grid; min-width: 0; align-content: center; gap: 5px; }
.asset-library__card strong,.asset-library__card small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.asset-library__card small { color: #969baa; font-size: 10px; font-weight: 450; }
.asset-library__card > svg { position: absolute; top: 7px; right: 7px; padding: 3px; border-radius: 50%; color: #fff; background: #6466ef; }
.asset-library__state { grid-column: 1/-1; display: grid; min-height: 130px; place-items: center; color: #999ead; font-size: 12px; }
.asset-library__paging { display: flex; min-height: 34px; grid-column: 1/-1; align-items: center; justify-content: center; gap: 7px; color: #989dab; font-size: 10px; }
.asset-library__paging svg { animation: asset-library-spin .8s linear infinite; }
@keyframes asset-library-spin { to { transform: rotate(360deg); } }
@keyframes asset-generation-shimmer { 55%,100% { transform: translateX(100%); } }
@keyframes asset-generation-pulse { 70%,100% { box-shadow: 0 0 0 7px rgb(93 95 240 / 0%); } }
.asset-dialog__footer { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 14px 22px 18px; background: #fbfbfd; box-shadow: 0 -10px 30px rgb(36 40 57 / 4%); }
.asset-dialog__footer > div,.asset-generation-options { display: flex; align-items: center; gap: 8px; }
.asset-generation-options :deep(.app-select:first-child) { width: 190px; }
@media (max-width: 720px) {
  .asset-dialog { width: 100%; border-radius: 0; }
  .asset-form-grid.is-character { grid-template-columns: 1fr; }
  .asset-mode > div,.asset-library__grid { grid-template-columns: 1fr; }
  .asset-library > header,.asset-dialog__footer { align-items: stretch; flex-direction: column; }
  .asset-generation-options { width: 100%; flex-wrap: wrap; }
  .asset-generation-options :deep(.app-select:first-child) { width: 100%; }
  .asset-generation-options :deep(.image-parameters) { width: 100%; }
  .asset-generation-history__list { grid-template-columns: 1fr; }
}
@media (hover: none) {
  .asset-generated-preview__edit { opacity: 1; transform: none; }
}
@media (prefers-reduced-motion: reduce) {
  .asset-backdrop-enter-active,.asset-backdrop-leave-active,.asset-drawer-enter-active,.asset-drawer-leave-active { transition-duration: .01ms; }
  .asset-generation-history__placeholder svg,.asset-library__paging svg,.asset-generated-preview__overlay svg,.asset-generated-preview__loader svg,.asset-generation-status svg,.asset-generated-preview__status i { animation: none !important; }
  .asset-generated-preview__viewer.is-generating::after,.asset-generated-preview__generating::before { animation: none; opacity: .35; transform: none; }
  .asset-generated-preview__viewer img,.asset-generated-preview__viewer > .asset-generated-preview__zoom,.asset-generated-preview__edit,.asset-generation-history__image img { transition-duration: .01ms; }
  .asset-generation-history__error svg,.asset-error-detail-enter-active,.asset-error-detail-leave-active { transition-duration: .01ms; }
}
</style>
