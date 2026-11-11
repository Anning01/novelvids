<script setup lang="ts">
import { tr } from '@/i18n'

import type { NodeProps } from '@vue-flow/core'
import type { MaterialMention, MaterialMentionMode, MaterialMentionOption } from '../components/materialMentionTypes'
import StoryboardSheetCard from '@/components/StoryboardSheetCard.vue'
import { boundPrompt, genericPrompt, modelPromptTexts, plainPrompt, resolveModelPrompt, type ModelPromptVersions, type OptimizationFacts } from '@/shared/sceneModelPrompt'
import { includeSheet, sheetReference } from '@/shared/storyboardSheetReference'
import { useSceneBlockingMap } from '@/shared/useSceneBlockingMap'
import { withBlockingReference } from '@/shared/sceneBlockingReference'
import type { AssetReferenceEdgeConfig, WorkbenchEdge, WorkbenchNode } from '../types/workbenchTypes'
import { computed, inject, markRaw, onScopeDispose, ref, watch } from 'vue'
import { Film, LoaderCircle, WandSparkles } from 'lucide-vue-next'
import type { Asset, Scene, Video, VideoGenerationModel } from '@/types'
import ResourceLibraryPicker from '@/features/resource-library/ResourceLibraryPicker.vue'
import type { VideoResource } from '@/features/resource-library/types'
import { notice } from '@/shared/notice'
import SceneVideoParameterPicker from '@/components/SceneVideoParameterPicker.vue'
import { disambiguateMaterialMentionNames, materialMentionAssetCategory } from '../components/materialMentionTypes'
import MediaGenerationModelSelector from '../components/MediaGenerationModelSelector.vue'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
import WorkbenchPromptEditorPanel from '../components/WorkbenchPromptEditorPanel.vue'
import WorkbenchVideoMedia from '../components/WorkbenchVideoMedia.vue'
import { assetSelectedImageCandidates, assetForWorkbenchNode } from '../config/assetConfig'
import {
  normalizeShotConfig,
  patchShotWorkbenchConfig,
  shotGenerationOptions,
  type ShotProjectDefaults,
  type ShotWorkbenchConfig,
} from '../config/shotConfig'
import { registerWorkbenchPromptAction } from '../prompt/promptActionRegistry'
import { registerWorkbenchNodeRun } from '../run/nodeRunRegistry'
import { promptEditorFromData, workbenchPromptEditorKey } from '../prompt/promptEditor'
import { sceneHasRunningVideo } from '../graph/videoVersions'
import { videoAspectRatio, videoCoverUrl, videoPixelSize, videoResolution } from '../graph/videoMedia'
import { useWorkbenchStore } from '../store/workbenchStore'
import { estimateVideoCost } from '@/shared/modelPricing'
import { buildVideoInputImageReferences, readVideoReferenceMedia, referencedVideoMedia, videoReferenceMentionSyntax } from '@/shared/scenePromptReferences'
import { TaskStatusEnum } from '@/types'

const props = defineProps<NodeProps>()
const store = useWorkbenchStore()
const promptEditor = inject(workbenchPromptEditorKey, null)
const scene = computed(() => props.data.scene as Scene)
const videos = computed(() => (props.data.videos || []) as Video[])
const videoModels = computed(() => (props.data.videoModelOptions || []) as VideoGenerationModel[])
const videoModelOptions = computed(() => videoModels.value.map(model => ({ value: model.config_id, label: model.name || model.model })))
const selectedModel = computed(() => videoModels.value.find(item => item.config_id === config.value.modelType) || null)
const projectDefaults = computed<ShotProjectDefaults>(() => (
  props.data.project_defaults as ShotProjectDefaults | undefined
) || { aspectRatio: '9:16', resolution: '720p' })
const description = ref('')
const prompt = ref('')
const config = ref<ShotWorkbenchConfig>(normalizeShotConfig(scene.value, projectDefaults.value))
const saving = ref(false)
const optimizing = ref(false)
let optimization: AbortController | undefined
onScopeDispose(() => optimization?.abort())
const activePromptModel = computed(() => {
  const saved = scene.value.metadata?.video_prompt_model
  if (typeof saved === 'string') return saved
  return [...modelPromptTexts(scene.value)].find(([, text]) => text === scene.value.prompt)?.[0] || ''
})
const sheetExcluded = computed(() => scene.value.metadata?.storyboard_sheet_excluded === true)
function renderPrompt(value: string, model: string, source = scene.value, excluded = sheetExcluded.value) {
  return config.value.useLastFrame ? plainPrompt(value, source) : boundPrompt(value, source, model, excluded)
}
function sceneMedia(source: Scene, excluded: boolean) {
  const saved = readVideoReferenceMedia(source.metadata?.video_reference_media)
  const sheet = sheetReference(source)
  return sheet && !excluded ? includeSheet(saved, sheet) : saved
}

const measuredVideoSize = ref<{ width: number; height: number } | null>(null)

watch([scene, projectDefaults], ([value, defaults], [previous]) => {
  const preserveInput = previous?.id === value.id && previous.prompt === value.prompt &&
    previous.metadata?.video_prompt_model === value.metadata?.video_prompt_model
  description.value = value.description || ''
  const next = normalizeShotConfig(value, defaults)
  if (!videoModels.value.some(item => item.config_id === next.modelType)) next.modelType = videoModels.value[0]?.config_id || null
  config.value = next
  if (!preserveInput) prompt.value = renderPrompt(value.prompt || '', activePromptModel.value, value)
}, { immediate: true })
watch(prompt, value => store.updateNodeDraft(props.id, { prompt_dirty: value !== (scene.value.prompt || '') }))
watch(videoModels, value => {
  if (!value.some(item => item.config_id === config.value.modelType)) {
    config.value.modelType = value[0]?.config_id || null
  }
}, { immediate: true })

const busy = computed(() => store.busySceneIds.includes(scene.value.id) || sceneHasRunningVideo(videos.value))
const promptEditorConfig = computed(() => promptEditorFromData(props.data.prompt_editor))
const promptEditorOpen = computed(() => props.data.prompt_editor_open === true && Boolean(promptEditorConfig.value))
const blockingMap = useSceneBlockingMap(() => promptEditorOpen.value ? scene.value : undefined)
const backendCanGenerate = computed(() => props.data.generate_capability === true)
const keyframesReady = computed(() => !config.value.useLastFrame || Boolean(config.value.firstFrameUrl && config.value.lastFrameUrl))
const generationMode = computed(() => config.value.useLastFrame ? 'keyframes' : 'reference')
const canGenerate = computed(() => Boolean(backendCanGenerate.value
  && selectedModel.value?.capabilities.generation_modes.includes(generationMode.value)
  && keyframesReady.value
  && !busy.value
  && !saving.value && !optimizing.value
  && (!activePromptModel.value || activePromptModel.value === selectedModel.value?.model_type)))
const activeVideoId = computed(() => {
  const configured = config.value.activeVideoId
  return configured && videos.value.some(video => video.id === configured) ? configured : videos.value[0]?.id || null
})
const activeVideo = computed(() => videos.value.find(video => video.id === activeVideoId.value) || videos.value[0] || null)
const activeVideoRunning = computed(() => Boolean(activeVideo.value
  && ![TaskStatusEnum.COMPLETED, TaskStatusEnum.FAILED, TaskStatusEnum.CANCELLED].includes(activeVideo.value.status)))
const activeVideoFailed = computed(() => Boolean(activeVideo.value
  && [TaskStatusEnum.FAILED, TaskStatusEnum.CANCELLED].includes(activeVideo.value.status)))
watch(activeVideoId, () => { measuredVideoSize.value = null })

const displayedVideoRatio = computed(() => {
  const measured = measuredVideoSize.value
  if (measured) return `${measured.width}:${measured.height}`
  return activeVideo.value ? videoAspectRatio(activeVideo.value) || config.value.aspectRatio : config.value.aspectRatio
})
const displayedVideoSize = computed(() => measuredVideoSize.value
  || (activeVideo.value ? videoPixelSize(activeVideo.value) : null))
const mediaSizeLabel = computed(() => {
  const resolution = activeVideo.value ? videoResolution(activeVideo.value) || config.value.resolution : config.value.resolution
  const declaredRatio = activeVideo.value ? videoAspectRatio(activeVideo.value) || config.value.aspectRatio : config.value.aspectRatio
  const size = displayedVideoSize.value
  const pixelSize = size ? `${Math.round(size.width)} × ${Math.round(size.height)}` : ''
  return [resolution, declaredRatio, pixelSize].filter(Boolean).join(' · ')
})
function mediaKindForNode(node: WorkbenchNode): MaterialMentionOption['mediaKind'] {
  if (node.kind === 'video_media' || node.kind === 'video_result') return 'video'
  if (node.kind === 'audio_media' || node.kind === 'audio_reference') return 'audio'
  if (node.kind === 'image_media' || node.kind === 'digital_human') return 'image'
  if (node.kind === 'asset') {
    const linkedAsset = assetForWorkbenchNode(node)
    return linkedAsset && assetSelectedImageCandidates(linkedAsset).length > 0 ? 'image' : 'text'
  }
  return 'text'
}

function previewUrlForNode(node: WorkbenchNode) {
  if (node.kind === 'asset') {
    const asset = assetForWorkbenchNode(node)
    const image = asset ? assetSelectedImageCandidates(asset).at(0) : undefined
    return image?.previewUrl || image?.thumbnailUrl || image?.url || ''
  }
  if (node.kind === 'digital_human')
    return (node.data.resource as { image_url?: string } | undefined)?.image_url || ''
  if (node.kind === 'audio_reference')
    return (node.data.resource as { avatar_url?: string } | undefined)?.avatar_url || ''
  return typeof node.data.url === 'string' ? node.data.url : ''
}

function promptForNode(node: WorkbenchNode) {
  if (node.kind === 'asset') {
    const asset = assetForWorkbenchNode(node)
    return asset?.description || asset?.base_traits || ''
  }
  return typeof node.data.prompt === 'string' ? node.data.prompt : ''
}

function referenceMode(edge: WorkbenchEdge, node: WorkbenchNode): MaterialMentionMode {
  const configured = (edge.config as AssetReferenceEdgeConfig | null)?.inputMode
  if (configured && configured !== 'auto') return configured
  if (node.kind === 'asset') {
    const localMode = config.value.referenceModes[String(node.id)]
    if (localMode === 'prompt') return 'prompt_injection'
    if (localMode === 'image') return 'reference_image'
  }
  const mediaKind = mediaKindForNode(node)
  if (mediaKind === 'video') return 'reference_video'
  if (mediaKind === 'audio') return 'reference_audio'
  if (mediaKind === 'image') return 'reference_image'
  return 'prompt_injection'
}

const referenceEdges = computed(() => store.edges
  .filter(edge => edge.type === 'asset_reference' && edge.target === props.id)
  .sort((left, right) => left.orderIndex - right.orderIndex || left.id - right.id))

const materialOptions = computed<MaterialMentionOption[]>(() => disambiguateMaterialMentionNames(
  referenceEdges.value.flatMap((edge) => {
    const source = store.nodeByKey(edge.source)
    if (!source) return []
    const mediaKind = mediaKindForNode(source)
    const previewUrl = previewUrlForNode(source)
    const base = {
      nodeKey: source.key,
      name: source.title.trim() || source.key,
      sourceName: source.title.trim() || source.key,
      prompt: promptForNode(source),
      previewUrl,
      hasImage: mediaKind === 'image' && Boolean(previewUrl),
      mediaKind,
      assetCategory: source.kind === 'asset'
        ? materialMentionAssetCategory((source.data.asset as Asset | undefined)?.asset_type)
        : source.kind === 'digital_human' ? 'person' as const : undefined,
    }
    if (source.kind !== 'asset' || referenceMode(edge, source) !== 'reference_image') return [base]
    const candidates = assetSelectedImageCandidates(assetForWorkbenchNode(source)!)
    if (candidates.length <= 1) return [base]
    return candidates.map(candidate => ({
      ...base,
      mentionKey: `${source.key}:image:${candidate.displayIndex}`,
      name: tr('{p0}-图{p1}', { p0: base.name, p1: candidate.displayIndex + 1 }),
      previewUrl: candidate.previewUrl || candidate.thumbnailUrl || candidate.url,
      hasImage: true,
      mediaKind: 'image' as const,
    }))
  }),
))

const materialMentions = computed<MaterialMention[]>(() => {
  const connected = disambiguateMaterialMentionNames(referenceEdges.value.flatMap((edge) => {
    const source = store.nodeByKey(edge.source)
    if (!source) return []
    return materialOptions.value
      .filter(option => option.nodeKey === edge.source)
      .map((option, index) => ({
        ...option,
        edgeKey: `${edge.key}:${option.mentionKey || index}`,
        connectionKey: edge.key,
        mode: referenceMode(edge, source),
      }))
  }))
  const refs = withBlockingReference(scene.value, sceneMedia(scene.value, sheetExcluded.value))
  const text = activePromptModel.value ? genericPrompt(scene.value) + '\n' + prompt.value : prompt.value
  const saved = referencedVideoMedia(text, refs)
    .map(reference => ({
      nodeKey: props.id,
      edgeKey: `saved:${videoReferenceMentionSyntax(reference)}`,
      syntax: videoReferenceMentionSyntax(reference),
      name: reference.name || (reference.type === 'image' ? tr('参考图片') : tr('参考视频')),
      prompt: '',
      previewUrl: reference.mention_url === scene.value.blocking_reference?.mention_url && scene.value.blocking_reference ? blockingMap.image.value : reference.url,
      hasImage: reference.type === 'image',
      mediaKind: reference.type,
      mode: reference.type === 'image' ? 'reference_image' as const : 'reference_video' as const,
    }))
  return [...connected, ...saved]
})
const editorMaterials = computed(() => [...materialOptions.value, ...materialMentions.value.filter(item => item.syntax)])
const referenceImageCount = computed(() => materialMentions.value.filter(item => item.mode === 'reference_image').length)
const referenceVideoCount = computed(() => materialMentions.value.filter(item => item.mode === 'reference_video').length)
const referenceAudioCount = computed(() => materialMentions.value.filter(item => item.mode === 'reference_audio').length)
const promptInjectionCount = computed(() => materialMentions.value.filter(item => item.mode === 'prompt_injection').length)
const assetInputSummary = computed(() => tr('图片 {p0}/9 · 视频 {p1}/3 · 音频 {p2}/3 · 提示词 {p3}', { p0: referenceImageCount.value, p1: referenceVideoCount.value, p2: referenceAudioCount.value, p3: promptInjectionCount.value }))
function normalizedDraftConfig(): ShotWorkbenchConfig {
  const duration = Math.max(1, Math.min(30, Number(config.value.duration) || 1))
  return {
    ...config.value,
    duration,
    modelType: config.value.modelType === null ? null : Number(config.value.modelType),
  }
}

async function save(metadata: Scene['metadata'] = {}, nextPrompt = prompt.value, source = scene.value) {
  saving.value = true
  try {
    const nextConfig = normalizedDraftConfig()
    config.value = nextConfig
    await store.saveScene(scene.value.id, {
      description: description.value,
      prompt: nextPrompt,
      duration: nextConfig.duration,
      asset_ids: referenceEdges.value
        .map(edge => store.nodeByKey(edge.source))
        .filter((node): node is WorkbenchNode => node?.kind === 'asset')
        .map(node => node.id),
      metadata: patchShotWorkbenchConfig({ ...source.metadata, ...metadata }, nextConfig),
    })
  } finally {
    saving.value = false
  }
}

function optimizationFacts(): OptimizationFacts {
  const cfg = config.value
  const submitted: OptimizationFacts['submitted_media'] = []
  if (cfg.useLastFrame) {
    if (cfg.firstFrameUrl) submitted.push({type: 'image', label: tr('首帧')})
    if (cfg.lastFrameUrl) submitted.push({type: 'image', label: tr('尾帧')})
  } else {
    const imageSources = referenceEdges.value.flatMap(edge => {
      const node = store.nodeByKey(edge.source)
      const asset = node?.kind === 'asset' && assetForWorkbenchNode(node)
      if (!asset) return []
      return [{assetId: asset.id, label: asset.canonical_name, mentionNames: [asset.canonical_name, ...(asset.aliases || [])],
        imageUrls: assetSelectedImageCandidates(asset).map(item => item.url)}]
    })
    const references = withBlockingReference(scene.value, sceneMedia(scene.value, sheetExcluded.value))
    for (const image of buildVideoInputImageReferences(prompt.value, imageSources, references, selectedModel.value?.capabilities.max_reference_images)) {
      submitted.push({type: 'image', label: image.label})
    }
    for (const ref of materialMentions.value) {
      if (ref.mode === 'reference_video') submitted.push({type: 'video', label: ref.name})
      if (ref.mode === 'reference_audio') submitted.push({type: 'audio', label: ref.name})
    }
  }
  return {generic_prompt: plainPrompt(prompt.value, scene.value), duration: cfg.duration,
    aspect_ratio: cfg.aspectRatio, generation_mode: generationMode.value, submitted_media: submitted}
}

function promptVersions(): ModelPromptVersions {
  return {...(scene.value.metadata?.video_prompt_versions as ModelPromptVersions || {})}
}

async function restoreGeneric() {
  const versions = promptVersions()
  const model = activePromptModel.value
  if (versions[model]) versions[model] = {...versions[model], prompt: plainPrompt(prompt.value, scene.value)}
  const generic = genericPrompt(scene.value)
  const text = renderPrompt(generic, '')
  await save({video_prompt_model: '', video_prompt_versions: versions}, text)
  prompt.value = text
}

async function togglePrompt() {
  if (saving.value || optimizing.value) return
  const controller = new AbortController()
  optimization = controller
  optimizing.value = true
  try {
    if (activePromptModel.value) { await restoreGeneric(); return }
    const model = selectedModel.value
    if (!model || !prompt.value.trim()) return
    const facts = optimizationFacts()
    const input = JSON.stringify(facts)
    const versions = promptVersions()
    const sourceId = scene.value.id
    const draft = await resolveModelPrompt(scene.value, model, facts, versions, controller.signal)
    if (controller.signal.aborted || sourceId !== scene.value.id || model.config_id !== selectedModel.value?.config_id) return
    if (input !== JSON.stringify(optimizationFacts())) {
      notice.info(tr('分镜内容已修改，请按当前内容重新优化'))
      return
    }
    versions[model.model_type] = {prompt: draft, input}
    const text = renderPrompt(draft, model.model_type)
    await save({generic_video_prompt: facts.generic_prompt, video_prompt_model: model.model_type, video_prompt_versions: versions}, text)
    prompt.value = text
  } catch (error) {
    if (!controller.signal.aborted) notice.error((error as Error).message)
  } finally {
    optimizing.value = false
  }
}

function rememberSheetTask(taskId: string) {
  // Closing the floating panel stops its poll. Reopening resumes from this task.
  const current = store.scenes.find(item => item.id === scene.value.id)
  if (!current) return
  const sheet = current.metadata?.storyboard_sheet as Record<string, unknown> | undefined
  current.metadata = {...current.metadata, storyboard_sheet: {...sheet, task_id: taskId, status: 'pending'}}
}

async function useSheet(source: Scene) {
  try {
    const text = renderPrompt(prompt.value, activePromptModel.value, source, false)
    await save({ storyboard_sheet_excluded: false, video_reference_media: sceneMedia(source, false) }, text, source)
    prompt.value = text
  } catch (error) { notice.error((error as Error).message) }
}

const libraryOpen = ref(false)
async function addLibraryReferences(items: VideoResource[]) {
  const existing = store.libraryVideoReferences(scene.value.id)
  const additions = items.filter(item => !existing.some(current => current.library_resource_id === item.id))
  const caps = selectedModel.value?.capabilities
  if (!caps || existing.length + additions.length > caps.max_reference_videos || existing.reduce((total, item) => total + (item.duration || 0), 0) + additions.reduce((total, item) => total + item.duration, 0) > caps.reference_video_total_duration_max + 0.001) {
    notice.error(tr('参考视频数量或总时长超过当前模型限制'))
    return
  }
  for (const resource of additions) {
    const target = store.nodeByKey(props.id)
    const item = store.addLibraryVideo(resource, { x: (target?.position.x || 0) - 430, y: (target?.position.y || 0) + existing.length * 60 })
    store.connectMediaNode(item.key, props.id)
  }
  libraryOpen.value = false
  notice.info(tr('视频已连接，请在提示词中通过 @ 选择引用'))
}

async function generate() {
  if (!canGenerate.value || config.value.modelType === null) return
  await save()
  await store.generateVideo(
    scene.value.id,
    config.value.modelType,
    shotGenerationOptions(config.value, selectedModel.value?.capabilities),
  )
}

registerWorkbenchPromptAction(props.id, {
  id: 'shot-video-generation',
  get label() { return tr('生成视频') },
  get busyLabel() { return tr('提交生成中') },
  enabled: canGenerate,
  busy,
  cost: computed(() => estimateVideoCost(
    selectedModel.value?.pricing,
    config.value.resolution,
    config.value.duration,
    referenceVideoCount.value > 0,
    0,
    generationMode.value === 'keyframes' ? 2 : referenceImageCount.value,
  )),
  costPricing: computed(() => selectedModel.value?.pricing),
  controls: [
    {
      id: 'shot-video-generation-model',
      component: markRaw(MediaGenerationModelSelector),
      props: computed(() => ({
        options: videoModelOptions.value,
        get label() { return tr('视频模型') },
      })),
      modelValue: computed(() => config.value.modelType),
      updateModelValue(value) {
        const modelType = Number(value)
        if (!Number.isFinite(modelType) || config.value.modelType === modelType) return
        optimization?.abort()
        config.value.modelType = modelType
        if (activePromptModel.value && activePromptModel.value !== selectedModel.value?.model_type && genericPrompt(scene.value)) {
          void restoreGeneric().catch(error => notice.error(error.message))
        }
      },
    },
    {
      id: 'shot-video-generation-parameters',
      component: markRaw(SceneVideoParameterPicker),
      props: computed(() => ({
        model: selectedModel.value,
        mode: generationMode.value,
        duration: config.value.duration,
        aspectRatio: config.value.aspectRatio,
        resolution: config.value.resolution,
        returnLastFrame: false,
        showReturnLastFrame: false,
      })),
      modelValue: computed(() => ({
        duration: config.value.duration,
        aspectRatio: config.value.aspectRatio,
        resolution: config.value.resolution,
      })),
      updateModelValue() {},
      events: {
        'update:duration': (value) => {
          const duration = Number(value)
          if (Number.isFinite(duration)) config.value.duration = duration
        },
        'update:aspectRatio': (value) => {
          if (typeof value === 'string') config.value.aspectRatio = value as ShotWorkbenchConfig['aspectRatio']
        },
        'update:resolution': (value) => {
          if (typeof value === 'string') config.value.resolution = value as ShotWorkbenchConfig['resolution']
        },
      },
    },
  ],
  run: generate,
})
registerWorkbenchNodeRun(props.id, { enabled: canGenerate, run: generate })

function addMaterialReference(material: MaterialMentionOption, nextPrompt: string) {
  if (!referenceEdges.value.some(edge => edge.source === material.nodeKey)
    && !materialMentions.value.some(item => item.syntax && item.syntax === material.syntax)) return
  prompt.value = nextPrompt
}

function handlePromptFocusOut(event: FocusEvent) {
  const panel = event.currentTarget as HTMLElement | null
  if (event.relatedTarget instanceof Node && panel?.contains(event.relatedTarget)) return
  void save()
}

watch([selectedModel, generationMode], ([model]) => {
  const capabilities = model?.capabilities
  if (!capabilities) return
  const ratios = capabilities.aspect_ratios_by_mode[generationMode.value] || capabilities.aspect_ratios
  if (!capabilities.resolutions.includes(config.value.resolution)) {
    config.value.resolution = (capabilities.resolutions.includes(capabilities.default_resolution)
      ? capabilities.default_resolution
      : capabilities.resolutions[0]) as ShotWorkbenchConfig['resolution']
  }
  if (!ratios.includes(config.value.aspectRatio)) {
    config.value.aspectRatio = (ratios.includes(capabilities.default_aspect_ratio)
      ? capabilities.default_aspect_ratio
      : ratios[0]) as ShotWorkbenchConfig['aspectRatio']
  }
  config.value.duration = Math.max(capabilities.duration_min, Math.min(capabilities.duration_max, config.value.duration))
  if (!capabilities.output_formats.includes(config.value.outputFormat)) {
    config.value.outputFormat = capabilities.default_output_format
  }
  if (!capabilities.supports_audio) config.value.generateAudio = false
}, { immediate: true })

</script>

<template>
  <div class="workbench-node-component">
    <ResourceLibraryPicker v-if="libraryOpen" :open="libraryOpen" :model-config-id="selectedModel?.config_id" :max-selection="selectedModel?.capabilities.max_reference_videos || 0" @close="libraryOpen = false" @choose="addLibraryReferences" />
    <WorkbenchNodeFrame
      v-bind="props"
      :data="{
        ...data,
        kind: 'shot',
        title: tr('视频 {p0}', { p0: String(scene.sequence).padStart(2, '0') }),
        status: busy ? 'running' : 'ready',
        body_flush: true,
        body_draggable: true,
        floating_header: true,
        borderless_media: true,
      }"
    >
      <template #toolbar-actions>
        <button
          type="button"
          :disabled="busy || config.useLastFrame || !selectedModel?.capabilities.max_reference_videos"
          :aria-label="tr('从资源库选择视频')"
          :title="tr('从资源库选择视频')"
          @click.stop="libraryOpen = true"
        >
          <Film :size="16" aria-hidden="true" />
        </button>
      </template>
      <template #meta>
        <span class="workbench-node-frame__media-size">{{ mediaSizeLabel }}</span>
        <span class="workbench-shot-media__asset-summary" :aria-label="tr('资产输入 {p0} 个，{p1}', { p0: referenceEdges.length, p1: assetInputSummary })">
          <strong>{{ tr('资产输入') }}</strong>
          <small>{{ referenceEdges.length }} {{ tr('个') }}</small>
          <span>{{ assetInputSummary }}</span>
        </span>
      </template>
      <div class="workbench-node-content workbench-media-node workbench-video-production">
        <WorkbenchVideoMedia
          :src="activeVideo?.url || ''"
          :poster="activeVideo ? videoCoverUrl(activeVideo) : ''"
          :title="tr('视频 {p0}', { p0: String(scene.sequence).padStart(2, '0') })"
          :ratio="displayedVideoRatio"
          :running="activeVideoRunning"
          :failed="activeVideoFailed"
          :error="activeVideoFailed ? tr('视频生成失败') : ''"
          :empty-label="tr('视频尚未生成')"
          @metadata="measuredVideoSize = $event"
        />
      </div>
    </WorkbenchNodeFrame>

    <WorkbenchPromptEditorPanel
      v-if="promptEditorConfig"
      :open="promptEditorOpen"
      :node-key="props.id"
      :config="promptEditorConfig"
      :model-value="prompt"
      :materials="editorMaterials"
      :mentions="materialMentions"
      @update:model-value="prompt = $event"
      @add="addMaterialReference"
      @close="promptEditor?.close(props.id)"
      @focus-reference="promptEditor?.focusReference($event)"
      @remove-reference="promptEditor?.removeReference($event)"
      @focusout="handlePromptFocusOut"
    >
      <template #header-actions>
        <StoryboardSheetCard v-if="store.projectConfig.storyboard_enabled || scene.metadata?.storyboard_sheet"
          :scene="scene" :enabled="Boolean(store.projectConfig.storyboard_enabled)" :can-use="sheetExcluded"
          :before-generate="() => save()" @submitted="rememberSheetTask" @updated="useSheet" @use="useSheet(scene)" />
      </template>
      <template #footer-actions>
        <button type="button" class="workbench-prompt-panel__secondary-action"
          :aria-pressed="Boolean(activePromptModel)" :aria-busy="optimizing"
          :disabled="saving || optimizing || (activePromptModel ? !genericPrompt(scene) : !selectedModel || !prompt.trim())"
          @click="togglePrompt">
          <LoaderCircle v-if="optimizing" class="workbench-prompt-panel__action-spinner" :size="13" />
          <WandSparkles v-else :size="13" />
          {{ optimizing ? tr('优化中') : activePromptModel ? tr('使用通用 Prompt') : tr('模型 Skills 优化') }}
        </button>
      </template>
    </WorkbenchPromptEditorPanel>
  </div>
</template>

<style scoped>
.workbench-video-production {
  position: relative;
  overflow: hidden;
  border-radius: 14px;
  background: transparent;
  gap: 0;
}
</style>
