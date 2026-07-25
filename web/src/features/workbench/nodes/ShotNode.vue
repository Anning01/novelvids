<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { ChevronDown, LoaderCircle, Pencil, Play, Save } from 'lucide-vue-next'
import { computed, inject, ref, watch } from 'vue'
import type { EnumItem, Scene, Video } from '@/types'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
import WorkbenchPromptEditorPanel from '../components/WorkbenchPromptEditorPanel.vue'
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
import { sceneAssetIds, sceneAssets } from '../graph/sceneAssets'
import { workbenchPromptEditorKey } from '../prompt/promptEditor'
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
const promptEditorOpen = computed(() => promptEditor?.activeNodeKey.value === props.id)
const backendCanGenerate = computed(() => props.data.generate_capability === true)
const canGenerate = computed(() => backendCanGenerate.value && config.value.modelType !== null && !busy.value && !saving.value)
const generationReason = computed(() => {
  if (!backendCanGenerate.value) return '当前服务未开放镜头视频生成'
  if (config.value.modelType === null) return '当前没有可用的视频模型'
  return '保存并生成镜头视频'
})
const referencedAssets = computed(() => sceneAssets(scene.value, store.assets))
const imageReferenceCount = computed(() => referencedAssets.value.filter(asset => asset.main_image).length)
const activeVideoId = computed(() => {
  const configured = config.value.activeVideoId
  return configured && videos.value.some(video => video.id === configured) ? configured : videos.value[0]?.id || null
})
const promptReferences = computed(() => referencedAssets.value.flatMap((asset) => {
  if (!asset.main_image) return []
  return [{
    key: String(asset.id),
    name: asset.canonical_name,
    url: asset.main_image,
    nodeKey: `asset-${asset.id}`,
    removable: true,
  }]
}))

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

function focusReference(nodeKey: string) {
  promptEditor?.close(props.id)
  store.selectNode(nodeKey)
}

async function removeReference(key: string) {
  const assetId = Number(key)
  if (!Number.isFinite(assetId)) return
  await store.saveScene(scene.value.id, {
    asset_ids: sceneAssetIds(scene.value).filter(id => id !== assetId),
  })
}

function referenceModeFor(assetId: number): ShotReferenceMode {
  return config.value.referenceModes[String(assetId)] || (store.assets.find(asset => asset.id === assetId)?.main_image ? 'image' : 'prompt')
}

function updateReferenceMode(assetId: number, event: Event) {
  const value = (event.target as HTMLSelectElement).value
  if (value !== 'prompt' && value !== 'image') return
  config.value.referenceModes = {
    ...config.value.referenceModes,
    [String(assetId)]: value,
  }
}

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
      <div class="workbench-shot-config">
        <label class="workbench-field">
          <span>画面描述</span>
          <textarea v-model="description" aria-label="画面描述" rows="2" />
        </label>

        <section class="workbench-prompt-summary">
          <div>
            <span>生成提示词</span>
            <button type="button" aria-label="打开生成提示词编辑器" @click.stop="promptEditor?.open(props.id)">
              <Pencil :size="13" aria-hidden="true" />编辑
            </button>
          </div>
          <p>{{ prompt || '暂未填写生成提示词' }}</p>
        </section>

        <section class="workbench-shot-reference-duration" aria-label="镜头参考时长">
          <span>参考时长</span><p>{{ scene.duration || 6 }} 秒</p>
        </section>

        <fieldset class="workbench-shot-generation-params">
          <legend>生成参数</legend>
          <label class="workbench-field workbench-shot-duration-field">
            <span>视频时长（秒）</span>
            <span class="workbench-shot-duration-control">
              <input v-model.number="config.duration" type="range" min="1" max="30" step="1" aria-label="视频时长（秒）">
              <input v-model.number="config.duration" type="number" min="1" max="30" step="1" aria-label="视频时长数值">
            </span>
            <output aria-label="视频时长（秒）当前值">{{ config.duration }} 秒</output>
          </label>
          <div class="workbench-form-row">
            <label class="workbench-field">
              <span>画面比例</span>
              <select v-model="config.aspectRatio" aria-label="画面比例">
                <option v-for="ratio in SHOT_ASPECT_RATIOS" :key="ratio" :value="ratio">{{ ratio }}</option>
              </select>
            </label>
            <label class="workbench-field">
              <span>分辨率</span>
              <select v-model="config.resolution" aria-label="分辨率">
                <option v-for="resolution in SHOT_RESOLUTIONS" :key="resolution" :value="resolution">{{ resolution }}</option>
              </select>
            </label>
          </div>
          <label class="workbench-field workbench-field--switch">
            <span>返回末帧图片</span>
            <input v-model="config.useLastFrame" type="checkbox" role="switch" aria-label="返回末帧图片">
            <small>开启后生成视频并将模型返回的末帧及时保存为独立图片。</small>
          </label>
          <div v-if="config.useLastFrame" class="workbench-form-row">
            <label class="workbench-field"><span>首帧图片</span><input v-model.trim="config.firstFrameUrl" aria-label="首帧图片 URL" placeholder="/path/to/first-frame.png"></label>
            <label class="workbench-field"><span>尾帧图片</span><input v-model.trim="config.lastFrameUrl" aria-label="尾帧图片 URL" placeholder="/path/to/last-frame.png"></label>
          </div>
        </fieldset>

        <section class="workbench-shot-assets" aria-label="资产引用策略">
          <button type="button" :aria-label="assetInputOpen ? '收起资产输入' : '展开资产输入'" :aria-expanded="assetInputOpen" @click="assetInputOpen = !assetInputOpen">
            <span><strong>资产输入</strong><small>{{ referencedAssets.length }} 个</small></span>
            <span>图片 {{ imageReferenceCount }}/9 · 视频 0/3 · 音频 0/3 · 提示词 {{ referencedAssets.length - imageReferenceCount }}</span>
            <ChevronDown :size="14" aria-hidden="true" />
          </button>
          <div v-if="assetInputOpen" class="workbench-shot-assets__list">
            <label v-for="asset in referencedAssets" :key="asset.id">
              <strong>{{ asset.canonical_name }}</strong>
              <select :value="referenceModeFor(asset.id)" :aria-label="`${asset.canonical_name}使用方式`" @change="updateReferenceMode(asset.id, $event)">
                <option value="prompt">提示词注入</option>
                <option value="image" :disabled="!asset.main_image">参考图片</option>
              </select>
            </label>
            <p v-if="!referencedAssets.length">尚未连接资产输入</p>
          </div>
        </section>

        <label class="workbench-field">
          <span>视频模型</span>
          <select v-model.number="config.modelType" aria-label="视频模型">
            <option v-for="option in options" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </label>

        <section v-if="videos.length" class="workbench-shot-versions" aria-label="镜头视频版本">
          <button
            v-for="(video, index) in videos"
            :key="video.id"
            type="button"
            :class="{ 'is-active': video.id === activeVideoId }"
            :aria-label="`采用视频 镜头 ${scene.sequence} 视频 ${index + 1}`"
            :aria-pressed="video.id === activeVideoId"
            @click="chooseVideo(video.id)"
          >
            <span>镜头 {{ scene.sequence }} 视频 {{ index + 1 }}</span><small>#{{ video.id }}</small>
          </button>
        </section>

        <footer class="workbench-node-actions workbench-shot-actions">
          <AppButton type="button" :disabled="saving || busy" @click="save">
            <LoaderCircle v-if="saving" class="is-spinning" :size="14" aria-hidden="true" /><Save v-else :size="14" aria-hidden="true" />{{ saving ? '保存中' : '保存' }}
          </AppButton>
          <AppButton type="button" class="is-primary" :disabled="!canGenerate" :title="generationReason" @click="generate">
            <LoaderCircle v-if="busy" class="is-spinning" :size="14" aria-hidden="true" /><Play v-else :size="14" aria-hidden="true" />{{ busy ? '生成中' : '保存并生成' }}
          </AppButton>
          <AppButton type="button" :disabled="!canGenerate" :title="generationReason" @click="generate">运行此配置</AppButton>
        </footer>
      </div>
    </WorkbenchNodeFrame>

    <WorkbenchPromptEditorPanel
      :open="promptEditorOpen"
      :node-key="props.id"
      label="镜头生成提示词"
      v-model="prompt"
      placeholder="描述镜头主体、动作、镜头运动、光线和风格…"
      hint="编辑区会跟随当前镜头，也可以进入专注模式"
      :busy="busy || saving"
      :run-enabled="canGenerate"
      :references="promptReferences"
      run-label="保存并生成视频"
      busy-label="处理中"
      @close="promptEditor?.close(props.id)"
      @save="save"
      @run="generate"
      @focus-reference="focusReference"
      @remove-reference="removeReference"
    />
  </div>
</template>
