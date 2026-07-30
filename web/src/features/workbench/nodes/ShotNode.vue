<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import type { MaterialMention, MaterialMentionMode, MaterialMentionOption } from '../components/materialMentionTypes'
import type { AssetReferenceEdgeConfig, WorkbenchEdge, WorkbenchNode } from '../types/workbenchTypes'
import { computed, inject, ref, watch } from 'vue'
import type { Asset, EnumItem, Scene, Video } from '@/types'
import { disambiguateMaterialMentionNames } from '../components/materialMentionTypes'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
import WorkbenchPromptEditorPanel from '../components/WorkbenchPromptEditorPanel.vue'
import WorkbenchSelect from '../components/WorkbenchSelect.vue'
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
import { useWorkbenchStore } from '../store/workbenchStore'

const props = defineProps<NodeProps>()
const store = useWorkbenchStore()
const promptEditor = inject(workbenchPromptEditorKey, null)
const scene = computed(() => props.data.scene as Scene)
const videos = computed(() => (props.data.videos || []) as Video[])
const options = computed(() => (props.data.modelOptions || []) as EnumItem[])
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
watch(options, value => {
  if (config.value.modelType === null && value.length) config.value.modelType = value[0].value
}, { immediate: true })

const busy = computed(() => store.busySceneIds.includes(scene.value.id))
const promptEditorConfig = computed(() => promptEditorFromData(props.data.prompt_editor))
const promptEditorOpen = computed(() => props.data.prompt_editor_open === true && Boolean(promptEditorConfig.value))
const backendCanGenerate = computed(() => props.data.generate_capability === true)
const canGenerate = computed(() => backendCanGenerate.value && config.value.modelType !== null && !busy.value && !saving.value)
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
  await store.generateVideo(scene.value.id, config.value.modelType, shotGenerationOptions(config.value))
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
const aspectRatioOptions = SHOT_ASPECT_RATIOS.map(value => ({ value, label: value }))
const resolutionOptions = SHOT_RESOLUTIONS.map(value => ({ value, label: value }))

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
            <span>视频时长（秒）</span>
            <div class="workbench-duration-slider nodrag nowheel">
              <input v-model.number="config.duration" type="range" min="1" max="30" step="1" aria-label="视频时长（秒）">
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
          <label class="workbench-field workbench-field--switch">
            <span>返回末帧图片</span>
            <button class="workbench-inline-switch" type="button" role="switch" aria-label="返回末帧图片" :aria-checked="config.useLastFrame" @click="config.useLastFrame = !config.useLastFrame"><i /></button>
            <small>开启后生成视频并将模型返回的末帧及时保存为独立图片。</small>
          </label>
        </fieldset>

        <section v-if="materialMentions.length" class="workbench-reference-list workbench-reference-list--compact" aria-label="资产引用策略">
          <button type="button" class="workbench-reference-list__toggle" :aria-label="assetInputOpen ? '收起资产输入' : '展开资产输入'" :aria-expanded="assetInputOpen" aria-controls="shot-asset-inputs" @click="assetInputOpen = !assetInputOpen">
            <span><strong>资产输入</strong><small>{{ materialMentions.length }} 个</small></span>
            <span>图片 {{ referenceImageCount }}/9 · 视频 {{ referenceVideoCount }}/3 · 音频 {{ referenceAudioCount }}/3 · 提示词 {{ promptInjectionCount }} <i aria-hidden="true">⌄</i></span>
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
</style>
