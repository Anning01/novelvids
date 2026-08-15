<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import type { MaterialMention, MaterialMentionMode, MaterialMentionOption } from '../components/materialMentionTypes'
import type { AssetReferenceEdgeConfig, WorkbenchEdge, WorkbenchNode } from '../types/workbenchTypes'
import { computed, inject, markRaw, ref, watch } from 'vue'
import type { Asset, Scene, Video, VideoGenerationModel } from '@/types'
import SceneVideoParameterPicker from '@/components/SceneVideoParameterPicker.vue'
import { disambiguateMaterialMentionNames, materialMentionAssetCategory } from '../components/materialMentionTypes'
import MediaGenerationModelSelector from '../components/MediaGenerationModelSelector.vue'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
import WorkbenchPromptEditorPanel from '../components/WorkbenchPromptEditorPanel.vue'
import WorkbenchVideoMedia from '../components/WorkbenchVideoMedia.vue'
import { assetSelectedImageCandidates } from '../config/assetConfig'
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
const measuredVideoSize = ref<{ width: number; height: number } | null>(null)

watch([scene, projectDefaults], ([value, defaults]) => {
  description.value = value.description || ''
  prompt.value = value.prompt || ''
  config.value = normalizeShotConfig(value, defaults)
}, { immediate: true })
watch(videoModels, value => {
  if (!value.some(item => item.config_id === config.value.modelType)) {
    config.value.modelType = value[0]?.config_id || null
  }
}, { immediate: true })

const busy = computed(() => store.busySceneIds.includes(scene.value.id) || sceneHasRunningVideo(videos.value))
const promptEditorConfig = computed(() => promptEditorFromData(props.data.prompt_editor))
const promptEditorOpen = computed(() => props.data.prompt_editor_open === true && Boolean(promptEditorConfig.value))
const backendCanGenerate = computed(() => props.data.generate_capability === true)
const keyframesReady = computed(() => !config.value.useLastFrame || Boolean(config.value.firstFrameUrl && config.value.lastFrameUrl))
const generationMode = computed(() => config.value.useLastFrame ? 'keyframes' : 'reference')
const canGenerate = computed(() => Boolean(backendCanGenerate.value
  && selectedModel.value?.capabilities.generation_modes.includes(generationMode.value)
  && keyframesReady.value
  && !busy.value
  && !saving.value))
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
    const linkedAsset = node.data.asset as Asset | undefined
    return linkedAsset && assetSelectedImageCandidates(linkedAsset).length > 0 ? 'image' : 'text'
  }
  return 'text'
}

function previewUrlForNode(node: WorkbenchNode) {
  if (node.kind === 'asset') {
    const asset = node.data.asset as Asset | undefined
    return asset ? assetSelectedImageCandidates(asset).at(0)?.url || '' : ''
  }
  if (node.kind === 'digital_human')
    return (node.data.resource as { image_url?: string } | undefined)?.image_url || ''
  if (node.kind === 'audio_reference')
    return (node.data.resource as { avatar_url?: string } | undefined)?.avatar_url || ''
  return typeof node.data.url === 'string' ? node.data.url : ''
}

function promptForNode(node: WorkbenchNode) {
  if (node.kind === 'asset') {
    const asset = node.data.asset as { description?: string; base_traits?: string } | undefined
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
    const candidates = assetSelectedImageCandidates(source.data.asset as Asset)
    if (candidates.length <= 1) return [base]
    return candidates.map(candidate => ({
      ...base,
      mentionKey: `${source.key}:image:${candidate.displayIndex}`,
      name: `${base.name}-图${candidate.displayIndex + 1}`,
      previewUrl: candidate.url,
      hasImage: true,
      mediaKind: 'image' as const,
    }))
  }),
))

const materialMentions = computed<MaterialMention[]>(() => {
  return disambiguateMaterialMentionNames(referenceEdges.value.flatMap((edge) => {
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
})
const referenceImageCount = computed(() => materialMentions.value.filter(item => item.mode === 'reference_image').length)
const referenceVideoCount = computed(() => materialMentions.value.filter(item => item.mode === 'reference_video').length)
const referenceAudioCount = computed(() => materialMentions.value.filter(item => item.mode === 'reference_audio').length)
const promptInjectionCount = computed(() => materialMentions.value.filter(item => item.mode === 'prompt_injection').length)
const assetInputSummary = computed(() => `图片 ${referenceImageCount.value}/9 · 视频 ${referenceVideoCount.value}/3 · 音频 ${referenceAudioCount.value}/3 · 提示词 ${promptInjectionCount.value}`)
function normalizedDraftConfig(): ShotWorkbenchConfig {
  const duration = Math.max(1, Math.min(30, Number(config.value.duration) || 1))
  return {
    ...config.value,
    duration,
    modelType: config.value.modelType === null ? null : Number(config.value.modelType),
  }
}

async function save() {
  saving.value = true
  try {
    const nextConfig = normalizedDraftConfig()
    config.value = nextConfig
    await store.saveScene(scene.value.id, {
      description: description.value,
      prompt: prompt.value,
      duration: nextConfig.duration,
      asset_ids: referenceEdges.value
        .map(edge => store.nodeByKey(edge.source))
        .filter((node): node is WorkbenchNode => node?.kind === 'asset')
        .map(node => node.id),
      metadata: patchShotWorkbenchConfig(scene.value.metadata, nextConfig),
    })
  } finally {
    saving.value = false
  }
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
  label: '生成视频',
  busyLabel: '提交生成中',
  enabled: canGenerate,
  busy,
  cost: computed(() => estimateVideoCost(
    selectedModel.value?.pricing,
    config.value.resolution,
    config.value.duration,
    referenceVideoCount.value > 0,
    0,
  )),
  controls: [
    {
      id: 'shot-video-generation-model',
      component: markRaw(MediaGenerationModelSelector),
      props: computed(() => ({
        options: videoModelOptions.value,
        label: '视频模型',
      })),
      modelValue: computed(() => config.value.modelType),
      updateModelValue(value) {
        const modelType = Number(value)
        if (Number.isFinite(modelType)) config.value.modelType = modelType
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
  if (!referenceEdges.value.some(edge => edge.source === material.nodeKey)) return
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
    <WorkbenchNodeFrame
      v-bind="props"
      :data="{
        ...data,
        kind: 'shot',
        title: `视频 ${String(scene.sequence).padStart(2, '0')}`,
        status: busy ? 'running' : 'ready',
        body_flush: true,
        body_draggable: true,
        floating_header: true,
        borderless_media: true,
      }"
    >
      <template #meta>
        <span class="workbench-node-frame__media-size">{{ mediaSizeLabel }}</span>
        <span class="workbench-shot-media__asset-summary" :aria-label="`资产输入 ${referenceEdges.length} 个，${assetInputSummary}`">
          <strong>资产输入</strong>
          <small>{{ referenceEdges.length }} 个</small>
          <span>{{ assetInputSummary }}</span>
        </span>
      </template>
      <div class="workbench-node-content workbench-media-node workbench-video-production">
        <WorkbenchVideoMedia
          :src="activeVideo?.url || ''"
          :poster="activeVideo ? videoCoverUrl(activeVideo) : ''"
          :title="`视频 ${String(scene.sequence).padStart(2, '0')}`"
          :ratio="displayedVideoRatio"
          :running="activeVideoRunning"
          :failed="activeVideoFailed"
          :error="activeVideoFailed ? '视频生成失败' : ''"
          empty-label="视频尚未生成"
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
      :materials="materialOptions"
      :mentions="materialMentions"
      @update:model-value="prompt = $event"
      @add="addMaterialReference"
      @close="promptEditor?.close(props.id)"
      @focus-reference="promptEditor?.focusReference($event)"
      @remove-reference="promptEditor?.removeReference($event)"
      @focusout="handlePromptFocusOut"
    />
  </div>
</template>

<style scoped>
.workbench-video-production {
  overflow: hidden;
  border-radius: 14px;
  background: transparent;
  gap: 0;
}
</style>
