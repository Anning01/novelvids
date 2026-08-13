<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import type { MaterialMention, MaterialMentionMode, MaterialMentionOption } from '../components/materialMentionTypes'
import type { AssetReferenceEdgeConfig, WorkbenchEdge, WorkbenchNode } from '../types/workbenchTypes'
import { computed, inject, ref, watch } from 'vue'
import type { Asset, EnumItem, Scene, Video, VideoGenerationModel } from '@/types'
import { disambiguateMaterialMentionNames } from '../components/materialMentionTypes'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
import WorkbenchPromptEditorPanel from '../components/WorkbenchPromptEditorPanel.vue'
import WorkbenchSelect from '../components/WorkbenchSelect.vue'
import MediaGenerationModelSelector from '../components/MediaGenerationModelSelector.vue'
import { assetSelectedImageCandidates } from '../config/assetConfig'
import {
  normalizeShotConfig,
  patchShotWorkbenchConfig,
  SHOT_ASPECT_RATIOS,
  SHOT_RESOLUTIONS,
  shotGenerationOptions,
  type ShotProjectDefaults,
  type ShotReferenceMode,
  type ShotWorkbenchConfig,
} from '../config/shotConfig'
import { registerWorkbenchPromptAction } from '../prompt/promptActionRegistry'
import { registerWorkbenchNodeRun } from '../run/nodeRunRegistry'
import { promptEditorFromData, workbenchPromptEditorKey } from '../prompt/promptEditor'
import { sceneHasRunningVideo } from '../graph/videoVersions'
import { useWorkbenchStore } from '../store/workbenchStore'

const props = defineProps<NodeProps>()
const store = useWorkbenchStore()
const promptEditor = inject(workbenchPromptEditorKey, null)
const scene = computed(() => props.data.scene as Scene)
const videos = computed(() => (props.data.videos || []) as Video[])
const options = computed(() => (props.data.modelOptions || []) as EnumItem[])
const videoModels = computed(() => (props.data.videoModelOptions || []) as VideoGenerationModel[])
const selectedModel = computed(() => videoModels.value.find(item => item.config_id === config.value.modelType) || null)
const projectDefaults = computed<ShotProjectDefaults>(() => (
  props.data.project_defaults as ShotProjectDefaults | undefined
) || { aspectRatio: '9:16', resolution: '720p' })
const description = ref('')
const prompt = ref('')
const config = ref<ShotWorkbenchConfig>(normalizeShotConfig(scene.value, projectDefaults.value))
const saving = ref(false)
const assetInputOpen = ref(false)

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
function mediaKindForNode(node: WorkbenchNode): MaterialMentionOption['mediaKind'] {
  if (node.kind === 'video_media' || node.kind === 'video_result') return 'video'
  if (node.kind === 'audio_media' || node.kind === 'audio_reference') return 'audio'
  if (node.kind === 'image_media' || node.kind === 'digital_human') return 'image'
  if (node.kind === 'asset')
    return (node.data.asset as { main_image?: string } | undefined)?.main_image ? 'image' : 'text'
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
      prompt: promptForNode(source),
      previewUrl,
      hasImage: mediaKind === 'image' && Boolean(previewUrl),
      mediaKind,
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
const frameImageOptions = computed(() => {
  const values = materialOptions.value.filter(option => option.hasImage && option.previewUrl)
  const configuredValues = [config.value.firstFrameUrl, config.value.lastFrameUrl].filter(Boolean)
  const seen = new Set<string>()
  return [
    { value: '', label: '请选择参考图片' },
    ...values.flatMap((option) => {
      if (seen.has(option.previewUrl)) return []
      seen.add(option.previewUrl)
      return [{ value: option.previewUrl, label: option.name }]
    }),
    ...configuredValues.flatMap((url) => {
      if (seen.has(url)) return []
      seen.add(url)
      return [{ value: url, label: '已保存的参考图片' }]
    }),
  ]
})

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
  label: '生成镜头',
  busyLabel: '提交生成中',
  enabled: canGenerate,
  busy,
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

function handleNodeFocusOut(event: FocusEvent) {
  const content = event.currentTarget as HTMLElement | null
  if (event.relatedTarget instanceof Node && content?.contains(event.relatedTarget)) return
  void save()
}

function materialInputModeOptions(material: MaterialMention) {
  if (material.mediaKind === 'video') return [{ value: 'reference_video', label: '参考视频' }]
  if (material.mediaKind === 'audio') return [{ value: 'reference_audio', label: '参考音频' }]
  if (material.mediaKind === 'image') {
    return [
      { value: 'prompt_injection', label: '提示词注入' },
      { value: 'reference_image', label: '参考图片' },
    ]
  }
  return [{ value: 'prompt_injection', label: '提示词注入' }]
}

function updateReferenceMode(material: MaterialMention, value: string) {
  if (!['prompt_injection', 'reference_image', 'reference_video', 'reference_audio'].includes(value)) return
  store.updateMediaEdgeConfig(material.edgeKey, {
    inputMode: value as AssetReferenceEdgeConfig['inputMode'],
    strategy: 'follow_primary',
  })
  const source = store.nodeByKey(material.nodeKey)
  if (source?.kind === 'asset') {
    const mode: ShotReferenceMode = value === 'reference_image' ? 'image' : 'prompt'
    config.value.referenceModes = { ...config.value.referenceModes, [String(source.id)]: mode }
  }
}

const referenceImageCount = computed(() => materialMentions.value.filter(item => item.mode === 'reference_image').length)
const referenceVideoCount = computed(() => materialMentions.value.filter(item => item.mode === 'reference_video').length)
const referenceAudioCount = computed(() => materialMentions.value.filter(item => item.mode === 'reference_audio').length)
const promptInjectionCount = computed(() => materialMentions.value.filter(item => item.mode === 'prompt_injection').length)
const supportedAspectRatios = computed(() => selectedModel.value?.capabilities.aspect_ratios_by_mode[generationMode.value]
  || selectedModel.value?.capabilities.aspect_ratios
  || [...SHOT_ASPECT_RATIOS])
const supportedResolutions = computed(() => selectedModel.value?.capabilities.resolutions || [...SHOT_RESOLUTIONS])
const aspectRatioOptions = computed(() => supportedAspectRatios.value.map(value => ({ value, label: value === 'adaptive' ? '自适应' : value })))
const resolutionOptions = computed(() => supportedResolutions.value.map(value => ({ value, label: value })))
const outputFormatOptions = computed(() => (selectedModel.value?.capabilities.output_formats || ['mp4']).map(value => ({ value, label: value.toUpperCase() })))
const durationMin = computed(() => selectedModel.value?.capabilities.duration_min || 4)
const durationMax = computed(() => selectedModel.value?.capabilities.duration_max || 30)
const maxReferenceImages = computed(() => selectedModel.value?.capabilities.max_reference_images || 0)

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

async function chooseVideo(videoId: number) {
  if (videoId === activeVideoId.value) return
  config.value.activeVideoId = videoId
  await store.setActiveVideo(scene.value.id, videoId)
}
</script>

<template>
  <div class="workbench-node-component">
    <WorkbenchNodeFrame
      v-bind="props"
      :data="{ ...data, kind: 'shot', title: `镜头 ${String(scene.sequence).padStart(2, '0')}`, status: busy ? 'running' : 'ready' }"
    >
      <div class="workbench-node-content" @focusout="handleNodeFocusOut">
        <div class="workbench-shot-reference__row workbench-shot-reference__row--duration" aria-label="镜头参考时长">
          <span>参考时长</span><p>{{ scene.duration || 6 }} 秒</p>
        </div>

        <fieldset class="workbench-form workbench-capability-form">
          <legend>生成参数</legend>
          <label class="workbench-field">
            <span>视频模型</span>
            <MediaGenerationModelSelector v-model="config.modelType" :options="options" label="视频模型" />
          </label>
          <label class="workbench-field">
            <span>视频时长（秒）</span>
            <div class="workbench-duration-slider nodrag nowheel">
              <input v-model.number="config.duration" type="range" :min="durationMin" :max="durationMax" step="1" aria-label="视频时长（秒）">
              <span :aria-label="`视频时长（秒）当前值`">{{ config.duration }} 秒</span>
            </div>
          </label>
          <label class="workbench-field">
            <span>画面比例</span>
            <WorkbenchSelect v-model="config.aspectRatio" :options="aspectRatioOptions" label="画面比例" />
          </label>
          <label class="workbench-field">
            <span>分辨率</span>
            <WorkbenchSelect v-model="config.resolution" :options="resolutionOptions" label="分辨率" />
          </label>
          <label class="workbench-field">
            <span>视频格式</span>
            <WorkbenchSelect v-model="config.outputFormat" :options="outputFormatOptions" label="视频格式" />
          </label>
          <label v-if="selectedModel?.capabilities.supports_audio" class="workbench-field workbench-field--switch">
            <span>同步音频</span>
            <button class="workbench-inline-switch" type="button" role="switch" aria-label="生成同步音频" :aria-checked="config.generateAudio" @click="config.generateAudio = !config.generateAudio"><i /></button>
            <small>由所选 Seedance 模型随视频生成音频。</small>
          </label>
          <label class="workbench-field workbench-field--switch">
            <span>首尾帧模式</span>
            <button class="workbench-inline-switch" type="button" role="switch" aria-label="首尾帧模式" :aria-checked="config.useLastFrame" @click="config.useLastFrame = !config.useLastFrame"><i /></button>
            <small>开启后从已连接的图片中指定首帧和尾帧。</small>
          </label>
          <template v-if="config.useLastFrame">
            <label class="workbench-field">
              <span>首帧图片</span>
              <WorkbenchSelect v-model="config.firstFrameUrl" :options="frameImageOptions" label="首帧图片" />
            </label>
            <label class="workbench-field">
              <span>尾帧图片</span>
              <WorkbenchSelect v-model="config.lastFrameUrl" :options="frameImageOptions" label="尾帧图片" />
            </label>
            <small v-if="!keyframesReady" class="workbench-field-error" role="alert">请先连接图片资产，并同时选择首帧和尾帧。</small>
          </template>
        </fieldset>

        <section v-if="materialMentions.length" class="workbench-reference-list workbench-reference-list--compact" aria-label="资产引用策略">
          <button type="button" class="workbench-reference-list__toggle" :aria-label="assetInputOpen ? '收起资产输入' : '展开资产输入'" :aria-expanded="assetInputOpen" aria-controls="shot-asset-inputs" @click="assetInputOpen = !assetInputOpen">
            <span><strong>资产输入</strong><small>{{ materialMentions.length }} 个</small></span>
            <span>图片 {{ referenceImageCount }}/{{ maxReferenceImages }} · 视频 {{ referenceVideoCount }}/3 · 音频 {{ referenceAudioCount }}/3 · 提示词 {{ promptInjectionCount }} <i aria-hidden="true">⌄</i></span>
          </button>
          <div v-if="assetInputOpen" id="shot-asset-inputs" class="workbench-reference-list__body">
            <div v-for="material in materialMentions" :key="material.edgeKey" class="workbench-shot-asset-input">
              <strong>{{ material.name }}</strong>
              <WorkbenchSelect
                :model-value="material.mode"
                :options="materialInputModeOptions(material)"
                :label="`${material.name}使用方式`"
                @update:model-value="updateReferenceMode(material, $event)"
              />
            </div>
          </div>
        </section>

        <section v-if="videos.length" class="workbench-result-list" aria-label="镜头视频版本">
          <button
            v-for="(video, index) in videos"
            :key="video.id"
            type="button"
            :class="{ 'is-current': video.id === activeVideoId }"
            :aria-label="`采用视频 镜头 ${scene.sequence} 视频 ${index + 1}`"
            :aria-pressed="video.id === activeVideoId"
            @click="chooseVideo(video.id)"
          >
            <span>镜头 {{ scene.sequence }} 视频 {{ index + 1 }}</span><small>#{{ video.id }}</small>
          </button>
        </section>
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
.workbench-inline-switch {
  position: relative;
  width: 34px;
  height: 20px;
  padding: 2px;
  border: 0;
  border-radius: 999px;
  background: #5b5651;
  cursor: pointer;
  transition: background 140ms ease;
}

.workbench-inline-switch[aria-checked='true'] {
  background: #9675ef;
}

.workbench-inline-switch > i {
  display: block;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #f3eee9;
  transition: transform 140ms ease;
}

.workbench-inline-switch[aria-checked='true'] > i {
  transform: translateX(14px);
}

.workbench-field-error {
  color: #e4a39a;
  font-size: 10px;
  line-height: 1.5;
}
</style>
