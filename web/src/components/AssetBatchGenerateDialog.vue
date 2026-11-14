<script setup lang="ts">
import { tr } from '@/i18n'

import { computed, ref, watch } from 'vue'
import { ImageIcon, ListChecks, LoaderCircle, Sparkles, X } from 'lucide-vue-next'
import AppBadge from '@/components/AppBadge.vue'
import AppButton from '@/components/AppButton.vue'
import BillingPriceTag from '@/components/BillingPriceTag.vue'
import AppSelect from '@/components/AppSelect.vue'
import ImageGenerationParameterPanel, { type ImageGenerationParameters } from '@/components/ImageGenerationParameterPanel.vue'
import { api } from '@/api'
import { notice } from '@/shared/notice'
import { estimateImageCost } from '@/shared/modelPricing'
import { AssetTypeEnum, type Asset, type ImageGenerationModel } from '@/types'

interface BatchGenerateOptions {
  assetIds: number[]
  variantIds: number[]
  modelConfigId: number
  concurrency: number
  clarity: string
  ratio: string
  outputFormat: string
  generationCount: number
}

const props = defineProps<{
  open: boolean
  assets: Asset[]
  generatingIds: Set<number>
  failedIds: Set<number>
  generatingTargets?: Set<string>
  failedTargets?: Set<string>
  submitting?: boolean
}>()
const emit = defineEmits<{ close: []; generate: [options: BatchGenerateOptions] }>()

const models = ref<ImageGenerationModel[]>([])
const modelId = ref('')
const imageParameters = ref<ImageGenerationParameters>({ clarity: '1.5K', aspectRatio: '16:9', outputFormat: 'png', generationCount: 1 })
const selectedIds = ref<string[]>([])
const loadingModels = ref(false)

const assetTypes = [
  { value: AssetTypeEnum.PERSON, get label() { return tr('角色') } },
  { value: AssetTypeEnum.SCENE, get label() { return tr('场景') } },
  { value: AssetTypeEnum.ITEM, get label() { return tr('道具') } },
] as const

const targets = computed(() => props.assets.flatMap(asset => [
  { key: `asset:${asset.id}`, assetId: asset.id, variantId: undefined as number | undefined,
    asset_type: asset.asset_type, name: asset.canonical_name, description: asset.description,
    form: tr('基础形象'), image: asset.main_image, thumbnail: asset.main_image_thumbnail, metadata: asset.metadata },
  ...(asset.variants || []).map(variant => ({
    key: `variant:${variant.id}`, assetId: asset.id, variantId: variant.id,
    asset_type: asset.asset_type, name: `${asset.canonical_name} · ${variant.name}`,
    description: variant.description, form: tr('衍生形态'), image: variant.images[0],
    thumbnail: variant.image_thumbnails?.[0], metadata: { ...asset.metadata, ...variant.metadata },
  })),
]))
type GenerationTarget = typeof targets.value[number]
const isGenerating = (target: GenerationTarget) => props.generatingTargets
  ? props.generatingTargets.has(target.key) : props.generatingIds.has(target.assetId)
const hasFailed = (target: GenerationTarget) => props.failedTargets
  ? props.failedTargets.has(target.key) : props.failedIds.has(target.assetId)
const eligibleAssets = computed(() => targets.value.filter(target => !target.image && !isGenerating(target)))
const selectedTargets = computed(() => eligibleAssets.value.filter(target => selectedIds.value.includes(target.key)))
const modelOptions = computed(() => models.value.map(item => ({ value: String(item.config_id), label: item.name || item.model || tr('生图模型 {p0}', { p0: item.config_id }) })))
const selectedModel = computed(() => models.value.find(item => String(item.config_id) === modelId.value) || null)
const estimatedCost = computed(() => estimateImageCost(
  selectedModel.value?.pricing,
  imageParameters.value.clarity,
  selectedTargets.value.length,
))
const allSelected = computed(() => Boolean(eligibleAssets.value.length) && eligibleAssets.value.every(asset => selectedIds.value.includes(asset.key)))
const canGenerate = computed(() => selectedTargets.value.length > 0 && Boolean(modelId.value) && !props.submitting)

function reset() {
  selectedIds.value = []
  imageParameters.value = { clarity: '1.5K', aspectRatio: '16:9', outputFormat: 'png', generationCount: 1 }
}

async function loadModels() {
  loadingModels.value = true
  try {
    const response = await api.imageGenerationModels()
    models.value = response.data
    modelId.value = String(models.value[0]?.config_id || '')
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    loadingModels.value = false
  }
}

function toggleAll() {
  selectedIds.value = allSelected.value ? [] : eligibleAssets.value.map(asset => asset.key)
}

function assetsForType(type: AssetTypeEnum) {
  return targets.value.filter(asset => asset.asset_type === type)
}

function eligibleAssetsForType(type: AssetTypeEnum) {
  return eligibleAssets.value.filter(asset => asset.asset_type === type)
}

function selectedCountForType(type: AssetTypeEnum) {
  return eligibleAssetsForType(type).filter(asset => selectedIds.value.includes(asset.key)).length
}

function typeFullySelected(type: AssetTypeEnum) {
  const eligible = eligibleAssetsForType(type)
  return Boolean(eligible.length) && eligible.every(asset => selectedIds.value.includes(asset.key))
}

function typePartiallySelected(type: AssetTypeEnum) {
  const selectedCount = selectedCountForType(type)
  return selectedCount > 0 && !typeFullySelected(type)
}

function toggleType(type: AssetTypeEnum) {
  const typeIds = new Set(eligibleAssetsForType(type).map(asset => asset.key))
  if (!typeIds.size) return
  selectedIds.value = typeFullySelected(type)
    ? selectedIds.value.filter(id => !typeIds.has(id))
    : [...new Set([...selectedIds.value, ...typeIds])]
}

function assetTypeLabel(type: AssetTypeEnum) {
  return assetTypes.find(item => item.value === type)?.label || tr('资产')
}

function submit() {
  if (!canGenerate.value) return
  const model = selectedModel.value
  emit('generate', {
    assetIds: selectedTargets.value.filter(target => target.variantId === undefined).map(target => target.assetId),
    variantIds: selectedTargets.value.flatMap(target => target.variantId === undefined ? [] : [target.variantId]),
    modelConfigId: Number(modelId.value),
    concurrency: model?.concurrency || 1,
    clarity: imageParameters.value.clarity,
    ratio: imageParameters.value.aspectRatio,
    outputFormat: imageParameters.value.outputFormat,
    generationCount: 1,
  })
}

watch(() => props.open, value => {
  if (!value) return
  reset()
  void loadModels()
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
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="batch-dialog-backdrop" @click.self="emit('close')">
      <section class="batch-dialog" role="dialog" aria-modal="true" :aria-label="tr('批量生成资产设定图')">
        <header class="batch-dialog__header">
          <span><ListChecks :size="21" /></span>
          <div><h2>{{ tr('批量生成资产设定图') }}</h2></div>
          <AppButton type="button" variant="ghost" size="sm" icon-only :aria-label="tr('关闭')" @click="emit('close')"><X :size="18" /></AppButton>
        </header>

        <div class="batch-dialog__body">
          <p>{{ tr('可一次选择角色、场景、道具的基础形象和衍生形态；已有图片或正在生成的项目会自动跳过。') }}</p>
          <div class="batch-types" role="group" :aria-label="tr('按资产类型选择')">
            <label
              v-for="type in assetTypes"
              :key="type.value"
              class="batch-type"
              :class="{ 'is-selected': typeFullySelected(type.value), 'is-partial': typePartiallySelected(type.value) }"
            >
              <input
                type="checkbox"
                class="batch-checkbox"
                :checked="typeFullySelected(type.value)"
                :indeterminate="typePartiallySelected(type.value)"
                :disabled="!eligibleAssetsForType(type.value).length"
                @change="toggleType(type.value)"
              />
              <span><strong>{{ type.label }}</strong><small>{{ selectedCountForType(type.value) }}/{{ eligibleAssetsForType(type.value).length }} {{ tr('待生成') }}</small></span>
              <AppBadge tone="neutral" size="sm">{{ tr('共') }} {{ assetsForType(type.value).length }} {{ tr('个') }}</AppBadge>
            </label>
          </div>
          <div class="batch-assets">
            <p v-if="!targets.length" class="batch-empty">{{ tr('请先添加角色、场景或道具资产') }}</p>
            <label
              v-for="target in targets"
              :key="target.key"
              class="batch-asset"
              :class="{ 'is-selected': selectedIds.includes(target.key), 'is-disabled': target.image || isGenerating(target) }"
            >
              <input
                v-model="selectedIds"
                type="checkbox"
                class="batch-checkbox"
                :value="target.key"
                :disabled="Boolean(target.image) || isGenerating(target)"
              />
              <span class="batch-thumb"><img v-if="target.image" :src="target.thumbnail || target.image" alt="" /><ImageIcon v-else :size="18" /></span>
              <span class="batch-copy"><strong :title="target.name">{{ target.name }}</strong><small>{{ assetTypeLabel(target.asset_type) }} · {{ target.form }} · {{ target.description || tr('尚未填写描述') }}</small></span>
              <AppBadge v-if="target.image" class="batch-status" tone="warning" size="sm">{{ tr('已完成，不重复生成') }}</AppBadge>
              <AppBadge v-else-if="isGenerating(target)" class="batch-status is-running" tone="accent" size="sm"><LoaderCircle :size="12" />{{ tr('生成中') }}</AppBadge>
              <AppBadge v-else-if="hasFailed(target)" class="batch-status" tone="danger" size="sm">{{ tr('上次失败，可重试') }}</AppBadge>
              <AppBadge v-else class="batch-status" tone="accent" size="sm">{{ tr('待生成') }}</AppBadge>
            </label>
          </div>
        </div>

        <footer class="batch-dialog__footer">
          <div class="batch-options">
            <AppSelect v-model="modelId" :options="modelOptions" :disabled="loadingModels" :ariaLabel="tr('选择生图模型')"><template #leading><Sparkles :size="14" /></template></AppSelect>
            <ImageGenerationParameterPanel v-model="imageParameters" :capabilities="selectedModel?.capabilities" />
          </div>
          <div class="batch-actions">
            <AppButton type="button" variant="soft" :disabled="!eligibleAssets.length" @click="toggleAll">{{ allSelected ? tr('取消全选') : tr('全选') }}</AppButton>
            <AppButton type="button" variant="secondary" @click="emit('close')">{{ tr('取消') }}</AppButton>
            <AppButton type="button" variant="primary" :disabled="!canGenerate" :loading="submitting" @click="submit"><Sparkles v-if="!submitting" :size="15" />{{ tr('生成') }} {{ selectedTargets.length }} {{ tr('个') }}<BillingPriceTag v-if="!submitting" :cost="estimatedCost" :pricing="selectedModel?.pricing" /></AppButton>
          </div>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.batch-dialog-backdrop { position: fixed; inset: 0; z-index: 125; display: grid; place-items: center; padding: 22px; background: rgb(30 33 46 / 54%); backdrop-filter: blur(8px); }
.batch-dialog { display: grid; width: min(900px,100%); max-height: min(760px,calc(100dvh - 44px)); grid-template-rows: auto minmax(0,1fr) auto; color: var(--app-text); overflow: hidden; border-radius: 24px; background: var(--app-surface); box-shadow: 0 34px 110px rgb(19 22 34 / 32%); }
.batch-dialog__header { display: grid; grid-template-columns: 44px 1fr 36px; align-items: center; gap: 12px; padding: 18px 22px; background: var(--app-surface-muted); }
.batch-dialog__header > span { display: grid; width: 44px; height: 44px; place-items: center; border-radius: 14px; color: var(--app-accent); background: var(--app-surface); box-shadow: 0 8px 22px rgb(73 75 159 / 10%); }
.batch-dialog__header h2 { margin: 2px 0 0; color: var(--app-text); font-size: 19px; }
.batch-dialog__body { min-height: 0; overflow: auto; padding: 16px 22px 18px; }
.batch-dialog__body > p { margin: 0 0 12px; color: var(--app-text-secondary); font-size: 12px; line-height: 1.6; }
.batch-types { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 9px; margin-bottom: 14px; }
.batch-type { display: grid; min-height: 58px; grid-template-columns: 22px minmax(0,1fr) auto; align-items: center; gap: 9px; padding: 9px 11px; border-radius: 13px; color: var(--app-text-secondary); background: var(--app-surface-muted); box-shadow: inset 0 0 0 1px var(--app-border); cursor: pointer; text-align: left; }
.batch-type > span:nth-child(2) { display: grid; min-width: 0; gap: 3px; }
.batch-type strong { font-size: 12px; }
.batch-type small { color: var(--app-text-secondary); font-size: 10px; font-weight: 500; }
.batch-type.is-selected,.batch-type.is-partial { color: var(--app-accent); background: var(--app-accent-soft); box-shadow: inset 0 0 0 1px var(--app-accent); }
.batch-assets { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 10px; padding: 2px 4px 12px 2px; scrollbar-width: thin; }
.batch-empty { grid-column: 1 / -1; margin: 24px 0; color: var(--app-text-secondary); font-size: 12px; text-align: center; }
.batch-asset { display: grid; width: 100%; height: auto; min-height: 78px; grid-template-columns: 22px 54px minmax(0,1fr) auto; align-items: center; gap: 10px; padding: 9px 11px; border-radius: 14px; color: var(--app-text); background: var(--app-surface-muted); cursor: pointer; box-shadow: inset 0 0 0 1px transparent; text-align: left; }
.batch-asset:hover:not(.is-disabled),.batch-asset.is-selected { color: var(--app-accent); background: var(--app-accent-soft); box-shadow: inset 0 0 0 1px var(--app-accent); }
.batch-asset.is-disabled { opacity: .66; }
.batch-checkbox { width: 18px; height: 18px; margin: 0; accent-color: var(--app-accent); cursor: pointer; }
.batch-checkbox:focus-visible { outline: 2px solid var(--app-accent); outline-offset: 3px; }
.batch-type:focus-within,.batch-asset:focus-within { outline: 2px solid var(--app-accent); outline-offset: 2px; }
.batch-checkbox:disabled,.batch-asset.is-disabled { cursor: not-allowed; }
.batch-thumb { display: grid; width: 54px; height: 58px; overflow: hidden; place-items: center; border-radius: 10px; color: var(--app-text-secondary); background: var(--app-fill-subtle); }
.batch-thumb img { width: 100%; height: 100%; object-fit: cover; }
.batch-copy { display: grid; min-width: 0; gap: 5px; }
.batch-copy strong,.batch-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.batch-copy strong { font-size: 12px; }
.batch-copy small { color: var(--app-text-secondary); font-size: 10px; font-weight: 450; }
.batch-status { white-space: nowrap; }
.batch-status.is-running svg { animation: batch-spin .8s linear infinite; }
.batch-dialog__footer { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 14px 22px 18px; background: var(--app-surface-muted); box-shadow: 0 -10px 30px rgb(36 40 57 / 4%); }
.batch-options,.batch-actions { display: flex; align-items: center; gap: 8px; }
.batch-options :deep(.app-select:first-child) { width: 220px; }
@keyframes batch-spin { to { transform: rotate(360deg); } }
@media (max-width: 760px) {
  .batch-dialog-backdrop { padding: 0; }
  .batch-dialog { width: 100%; height: 100dvh; max-height: 100dvh; border-radius: 0; }
  .batch-types { grid-template-columns: 1fr; }
  .batch-assets { grid-template-columns: 1fr; }
  .batch-dialog__footer { align-items: stretch; flex-direction: column; }
  .batch-options,.batch-actions { width: 100%; flex-wrap: wrap; }
  .batch-options :deep(.app-select:first-child) { flex: 1; width: auto; }
  .batch-actions :deep(.app-button) { flex: 1; }
}
</style>
