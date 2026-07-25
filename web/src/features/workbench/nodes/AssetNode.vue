<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { ChevronDown, Image, LoaderCircle, Pencil, Play, Save, ScanFace } from 'lucide-vue-next'
import { computed, inject, ref, watch } from 'vue'
import type { Asset, DigitalHuman } from '@/types'
import { AssetTypeEnum } from '@/types'
import AppSelect from '@/components/AppSelect.vue'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
import MediaLibraryPicker from '../components/MediaLibraryPicker.vue'
import WorkbenchPromptEditorPanel from '../components/WorkbenchPromptEditorPanel.vue'
import {
  ASSET_SIZE_PRESETS,
  ASSET_TYPE_OPTIONS,
  assetImageCandidates,
  assetSizeResolution,
  normalizeAssetConfig,
  patchAssetWorkbenchConfig,
  type AssetWorkbenchConfig,
} from '../config/assetConfig'
import { workbenchPromptEditorKey } from '../prompt/promptEditor'
import { useWorkbenchStore } from '../store/workbenchStore'

const props = defineProps<NodeProps>()
const store = useWorkbenchStore()
const promptEditor = inject(workbenchPromptEditorKey, null)
const asset = computed(() => props.data.asset as Asset)
const assetType = ref<AssetTypeEnum>(AssetTypeEnum.PERSON)
const nickname = ref('')
const description = ref('')
const config = ref<AssetWorkbenchConfig>(normalizeAssetConfig(asset.value))
const saving = ref(false)
const changingMainImage = ref(false)
const digitalHumanPickerOpen = ref(false)

watch(asset, value => {
  assetType.value = value.asset_type
  nickname.value = value.canonical_name
  description.value = value.description || ''
  config.value = normalizeAssetConfig(value)
}, { immediate: true })

const busy = computed(() => store.busyAssetIds.includes(asset.value.id))
const promptEditorOpen = computed(() => promptEditor?.activeNodeKey.value === props.id)
const candidates = computed(() => assetImageCandidates(asset.value))
const personAsset = computed(() => assetType.value === AssetTypeEnum.PERSON)
const backendCanGenerate = computed(() => props.data.generate_capability === true)
const generatorSupportsType = computed(() => ![AssetTypeEnum.PRODUCT, AssetTypeEnum.STYLE].includes(assetType.value))
const canGenerate = computed(() => backendCanGenerate.value && generatorSupportsType.value && !busy.value && !saving.value)
const generationReason = computed(() => {
  if (!backendCanGenerate.value) return '当前服务未开放资产图片生成'
  if (!generatorSupportsType.value) return '当前后端未声明商品或风格资产的图片生成能力'
  return '保存并生成资产图片'
})
const sizeOptions = ASSET_SIZE_PRESETS.map(item => ({
  value: item.value,
  label: `${item.value} ${item.resolution} · ${item.ratio} · ${item.dimensions}${item.default ? '（默认）' : item.resolution === '2K' ? '（成本约 2 倍）' : ''}`,
}))
const selectedSizePreset = computed({
  get: () => ASSET_SIZE_PRESETS.some(item => item.value === config.value.size) ? config.value.size : '',
  set: (value: string) => {
    if (!value) return
    config.value.size = value
    config.value.resolution = assetSizeResolution(value)
  },
})

function normalizedDraftConfig(): AssetWorkbenchConfig {
  const count = Math.max(1, Math.min(4, Number(config.value.generationCount) || 1)) as AssetWorkbenchConfig['generationCount']
  const size = /^\d{2,5}x\d{2,5}$/.test(config.value.size.trim()) ? config.value.size.trim() : '1424x800'
  return {
    ...config.value,
    generationCount: count,
    resolution: assetSizeResolution(size),
    size,
    format: 'PNG',
    digitalHumanAssetId: personAsset.value ? config.value.digitalHumanAssetId : '',
  }
}

async function save() {
  saving.value = true
  try {
    const nextConfig = normalizedDraftConfig()
    config.value = nextConfig
    await store.saveAsset(asset.value.id, {
      asset_type: assetType.value,
      canonical_name: nickname.value.trim() || asset.value.canonical_name,
      description: description.value,
      metadata: patchAssetWorkbenchConfig(asset.value.metadata, nextConfig),
    })
  } finally {
    saving.value = false
  }
}

async function generate() {
  if (!canGenerate.value) return
  await save()
  await store.generateAsset(asset.value.id)
}

async function setMainImage(url: string) {
  if (changingMainImage.value || url === asset.value.main_image) return
  changingMainImage.value = true
  try {
    await store.setAssetMainImage(asset.value.id, url)
  } finally {
    changingMainImage.value = false
  }
}

function chooseDigitalHuman(item: DigitalHuman) {
  config.value.digitalHumanAssetId = item.asset_id
  digitalHumanPickerOpen.value = false
}
</script>

<template>
  <div class="workbench-node-component">
    <WorkbenchNodeFrame v-bind="props" :data="{ ...data, kind: 'asset', title: nickname || asset.canonical_name, status: busy ? 'running' : 'ready' }">
      <div class="workbench-asset-config">
        <div class="workbench-asset-config__identity">
          <label class="workbench-field">
            <span>资产类型</span>
            <select v-model.number="assetType" aria-label="资产类型">
              <option v-for="option in ASSET_TYPE_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
          </label>
          <label class="workbench-field">
            <span>昵称</span>
            <input v-model="nickname" aria-label="资产昵称" maxlength="80">
          </label>
        </div>

        <section class="workbench-asset-config__generation" aria-label="资产图片生成">
          <header><strong>图片生成</strong><small>已合并历史生成配置</small></header>
          <div v-if="personAsset" class="workbench-asset-digital-human">
            <div><strong>数字人人物</strong><small>可选 · 作为人物参考传入生图模型</small></div>
            <button type="button" :aria-label="config.digitalHumanAssetId ? `已选择数字人 ${config.digitalHumanAssetId}` : '从数字人库选择 选择后将占用 1 个参考图片名额'" @click="digitalHumanPickerOpen = true">
              <ScanFace :size="16" aria-hidden="true" />
              <span><strong>{{ config.digitalHumanAssetId || '从数字人库选择' }}</strong><small>选择后将占用 1 个参考图片名额</small></span>
            </button>
          </div>

          <fieldset class="workbench-asset-generation-params">
            <legend>生成参数</legend>
            <label class="workbench-field">
              <span>数量</span>
              <input v-model.number="config.generationCount" type="number" min="1" max="4" step="1" aria-label="数量">
            </label>
            <label class="workbench-field workbench-asset-size-field">
              <span>尺寸</span>
              <span class="workbench-asset-size-control">
                <input v-model.trim="config.size" aria-label="尺寸" inputmode="numeric" placeholder="1424x800">
                <AppSelect v-model="selectedSizePreset" class="workbench-asset-size-select" ariaLabel="尺寸推荐值" :options="sizeOptions" :menu-width="330" :max-menu-height="430">
                  <template #leading><ChevronDown :size="14" aria-hidden="true" /></template>
                </AppSelect>
              </span>
            </label>
            <p class="workbench-asset-size-hint">推荐使用 1K；2K 生成成本约为 1K 的 2 倍。也可输入自定义宽高，如 1280x960。</p>
            <label class="workbench-field">
              <span>格式</span>
              <select v-model="config.format" aria-label="格式"><option value="PNG">PNG</option></select>
            </label>
          </fieldset>
        </section>

        <div v-if="candidates.length" class="workbench-asset-candidates" aria-label="图片候选">
          <figure v-for="(candidate, index) in candidates" :key="candidate.url">
            <img :src="candidate.url" :alt="`候选图片 ${index + 1}`" loading="lazy" decoding="async">
            <button type="button" :aria-label="candidate.isMain ? `候选图片 ${index + 1} 当前为主图` : `设候选图片 ${index + 1}为主图`" :aria-pressed="candidate.isMain" :disabled="candidate.isMain || changingMainImage" @click="setMainImage(candidate.url)">
              {{ candidate.isMain ? '当前主图' : '设为主图' }}
            </button>
          </figure>
        </div>
        <div v-else class="workbench-media-placeholder"><Image :size="22" aria-hidden="true" />尚未生成主图</div>

        <div class="workbench-prompt-summary">
          <div><span>资产视觉描述</span><button type="button" aria-label="打开资产视觉描述编辑器" @click.stop="promptEditor?.open(props.id)"><Pencil :size="13" aria-hidden="true" />编辑</button></div>
          <p>{{ description || asset.base_traits || '暂无视觉描述' }}</p>
        </div>

        <footer class="workbench-asset-config__actions">
          <button type="button" :disabled="saving || busy" @click="save"><LoaderCircle v-if="saving" class="is-spinning" :size="14" aria-hidden="true" /><Save v-else :size="14" aria-hidden="true" />{{ saving ? '保存中' : '保存配置' }}</button>
          <button class="is-primary" type="button" :disabled="!canGenerate" :title="generationReason" @click="generate"><LoaderCircle v-if="busy" class="is-spinning" :size="14" aria-hidden="true" /><Play v-else :size="14" aria-hidden="true" />{{ busy ? '生成中' : '生成图片' }}</button>
        </footer>
      </div>
    </WorkbenchNodeFrame>

    <WorkbenchPromptEditorPanel
      :open="promptEditorOpen"
      :node-key="props.id"
      label="资产视觉描述"
      v-model="description"
      placeholder="描述人物、场景或道具的稳定视觉特征…"
      hint="保存后可直接使用当前描述重新生成资产主图"
      :busy="busy || saving"
      :run-enabled="canGenerate"
      :references="candidates.map((item, index) => ({ key: item.key, name: `${asset.canonical_name}候选图 ${index + 1}`, url: item.url }))"
      save-label="保存描述"
      run-label="保存并生成主图"
      busy-label="处理中"
      @close="promptEditor?.close(props.id)"
      @save="save"
      @run="generate"
    />

    <MediaLibraryPicker
      :open="digitalHumanPickerOpen"
      kind="digital-human"
      :selected-asset-id="config.digitalHumanAssetId"
      @close="digitalHumanPickerOpen = false"
      @choose="chooseDigitalHuman($event as DigitalHuman)"
    />
  </div>
</template>
