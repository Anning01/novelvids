<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import type { MaterialMention, MaterialMentionOption } from '../components/materialMentionTypes'
import type { ImageAnnotation, WorkbenchNode } from '../types/workbenchTypes'
import { Download, ImageUp, LoaderCircle, Pencil, Plus, ScanFace, Trash2 } from 'lucide-vue-next'
import { computed, inject, ref, watch } from 'vue'
import type { Asset, DigitalHuman } from '@/types'
import { AssetTypeEnum } from '@/types'
import { downloadFile } from '@/shared/downloadFile'
import { notice } from '@/shared/notice'
import ImageAnnotationDialog from '../components/ImageAnnotationDialog.vue'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
import MediaLibraryPicker from '../components/MediaLibraryPicker.vue'
import WorkbenchPromptEditorPanel from '../components/WorkbenchPromptEditorPanel.vue'
import WorkbenchSelect from '../components/WorkbenchSelect.vue'
import WorkbenchSuggestedInput from '../components/WorkbenchSuggestedInput.vue'
import { assetTypeIconFor, assetTypePresentationOptions } from '../components/assetTypePresentation'
import { disambiguateMaterialMentionNames } from '../components/materialMentionTypes'
import {
  ASSET_SIZE_PRESETS,
  assetImageMediaMetadata,
  assetImageCandidates,
  assetSizeResolution,
  normalizeAssetConfig,
  patchAssetImageMediaMetadata,
  patchAssetWorkbenchConfig,
  type AssetWorkbenchConfig,
} from '../config/assetConfig'
import { registerWorkbenchPromptAction } from '../prompt/promptActionRegistry'
import { registerWorkbenchNodeRun } from '../run/nodeRunRegistry'
import { promptEditorFromData, workbenchPromptEditorKey } from '../prompt/promptEditor'
import { useWorkbenchStore } from '../store/workbenchStore'

const props = defineProps<NodeProps>()
const store = useWorkbenchStore()
const promptEditor = inject(workbenchPromptEditorKey, null)
const asset = computed(() => props.data.asset as Asset)
const assetType = ref<AssetTypeEnum>(AssetTypeEnum.PERSON)
const assetTypeExplicit = ref(true)
const nickname = ref('')
const description = ref('')
const config = ref<AssetWorkbenchConfig>(normalizeAssetConfig(asset.value))
const saving = ref(false)
const changingMainImage = ref(false)
const uploadingImage = ref(false)
const downloadingImage = ref(false)
const annotationOpen = ref(false)
const loadedImageWidth = ref(0)
const loadedImageHeight = ref(0)
const digitalHumanPickerOpen = ref(false)
const selectedVariantValue = ref('base')
const addingVariant = ref(false)
const variantName = ref('')
const creatingVariant = ref(false)

watch(asset, value => {
  assetType.value = value.asset_type
  const media = assetImageMediaMetadata(value)
  assetTypeExplicit.value = media.source !== 'upload' || media.assetTypeExplicit === true
  nickname.value = value.canonical_name
  description.value = value.description || ''
  config.value = normalizeAssetConfig(value)
  if (
    selectedVariantValue.value !== 'base'
    && !value.variants?.some(variant => String(variant.id) === selectedVariantValue.value)
  ) selectedVariantValue.value = 'base'
}, { immediate: true })

const busy = computed(() => store.busyAssetIds.includes(asset.value.id))
const promptEditorConfig = computed(() => promptEditorFromData(props.data.prompt_editor))
const promptEditorOpen = computed(() => props.data.prompt_editor_open === true && Boolean(promptEditorConfig.value))
const candidates = computed(() => assetImageCandidates(asset.value))
const secondaryCandidates = computed(() => candidates.value.filter(candidate => !candidate.isMain))
const imageMetadata = computed(() => assetImageMediaMetadata(asset.value))
const annotations = computed(() => imageMetadata.value.annotations || [])
const imagePixelSize = computed(() => {
  const width = imageMetadata.value.width || loadedImageWidth.value
  const height = imageMetadata.value.height || loadedImageHeight.value
  return width > 0 && height > 0 ? `${Math.round(width)} × ${Math.round(height)}` : ''
})
const imageDownloadFilename = computed(() => {
  const extension = imageMetadata.value.mimeType?.includes('webp')
    ? 'webp'
    : imageMetadata.value.mimeType?.includes('jpeg')
      ? 'jpg'
      : asset.value.main_image?.match(/\.([a-z0-9]{2,5})(?:[?#]|$)/i)?.[1]?.toLowerCase() || 'png'
  const safeName = (nickname.value.trim() || asset.value.canonical_name || `asset-${asset.value.id}`)
    .replace(/[\\/:*?"<>|]+/g, '-')
  return `${safeName}.${extension}`
})
const variantOptions = computed(() => [
  { value: 'base', label: '基础形态' },
  ...(asset.value.variants || []).map(variant => ({
    value: String(variant.id),
    label: `${variant.name} · ${variant.images.length} 图`,
  })),
])
const selectedVariantId = computed(() => selectedVariantValue.value === 'base' ? undefined : Number(selectedVariantValue.value))
const referenceEdges = computed(() => store.edges
  .filter(edge => edge.type === 'asset_reference' && edge.target === props.id)
  .sort((left, right) => left.orderIndex - right.orderIndex || left.id - right.id))
function assetReferencePreview(node: WorkbenchNode) {
  if (node.kind === 'asset') return (node.data.asset as { main_image?: string } | undefined)?.main_image || ''
  if (node.kind === 'digital_human') return (node.data.resource as { image_url?: string } | undefined)?.image_url || ''
  return typeof node.data.url === 'string' ? node.data.url : ''
}
const materialOptions = computed<MaterialMentionOption[]>(() => disambiguateMaterialMentionNames(
  referenceEdges.value.flatMap((edge) => {
    const source = store.nodeByKey(edge.source)
    if (!source) return []
    const previewUrl = assetReferencePreview(source)
    return [{
      nodeKey: source.key,
      name: source.title.trim() || source.key,
      prompt: '',
      previewUrl,
      hasImage: Boolean(previewUrl),
      mediaKind: 'image' as const,
    }]
  }),
))
const materialMentions = computed<MaterialMention[]>(() => {
  const optionByNode = new Map(materialOptions.value.map(option => [option.nodeKey, option]))
  return referenceEdges.value.flatMap((edge) => {
    const option = optionByNode.get(edge.source)
    return option ? [{ ...option, edgeKey: edge.key, connectionKey: edge.key, mode: 'reference_image' as const }] : []
  })
})
const personAsset = computed(() => assetType.value === AssetTypeEnum.PERSON)
const backendCanGenerate = computed(() => props.data.generate_capability === true)
const generatorSupportsType = computed(() => ![AssetTypeEnum.PRODUCT, AssetTypeEnum.STYLE].includes(assetType.value))
const canGenerate = computed(() => backendCanGenerate.value && generatorSupportsType.value && !busy.value && !saving.value)
const sizeSuggestions = ASSET_SIZE_PRESETS.map(item => ({
  value: item.value,
  label: `${item.resolution} · ${item.ratio} · ${item.dimensions}${item.default ? '（默认）' : item.resolution === '2K' ? '（成本约 2 倍）' : ''}`,
}))
const assetTypeOptions = assetTypePresentationOptions
const assetTypeValue = computed({
  get: () => imageMetadata.value.source === 'upload' && !assetTypeExplicit.value ? 'image' : String(assetType.value),
  set: (value) => {
    if (value === 'image') {
      assetTypeExplicit.value = false
      void save()
      return
    }
    assetType.value = Number(value) as AssetTypeEnum
    assetTypeExplicit.value = true
    void save()
  },
})
function updateSize(value: string) {
  config.value.size = value
  config.value.resolution = assetSizeResolution(value)
}

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
    digitalHumanPreviewUrl: personAsset.value ? config.value.digitalHumanPreviewUrl : '',
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
      metadata: patchAssetImageMediaMetadata(
        patchAssetWorkbenchConfig(asset.value.metadata, nextConfig),
        { assetTypeExplicit: assetTypeExplicit.value },
      ),
    })
  } finally {
    saving.value = false
  }
}

async function generate() {
  if (!canGenerate.value) return
  await save()
  await store.generateAsset(asset.value.id, selectedVariantId.value)
}

async function createVariant() {
  const nextName = variantName.value.trim()
  if (!nextName || creatingVariant.value) return
  creatingVariant.value = true
  try {
    const created = await store.createAssetVariant(asset.value.id, {
      name: nextName,
      description: description.value,
      base_traits: asset.value.base_traits,
      chapter_numbers: store.chapter?.number ? [store.chapter.number] : [],
      metadata: { workbench: { ...config.value } },
    })
    selectedVariantValue.value = String(created.id)
    variantName.value = ''
    addingVariant.value = false
  } finally {
    creatingVariant.value = false
  }
}

async function deleteSelectedVariant() {
  const variantId = selectedVariantId.value
  if (!variantId) return
  await store.deleteAssetVariant(asset.value.id, variantId)
  selectedVariantValue.value = 'base'
}

registerWorkbenchPromptAction(props.id, {
  id: 'asset-image-generation',
  label: '生成资产图片',
  busyLabel: '生成中',
  enabled: canGenerate,
  busy,
  run: generate,
})
registerWorkbenchNodeRun(props.id, { enabled: canGenerate, run: generate })

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

function addMaterialReference(material: MaterialMentionOption, nextPrompt: string) {
  if (!referenceEdges.value.some(edge => edge.source === material.nodeKey)) return
  description.value = nextPrompt
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

async function replaceImage(event: Event) {
  const input = event.currentTarget as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || uploadingImage.value) return
  uploadingImage.value = true
  try {
    await store.replaceAssetImage(asset.value.id, file)
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '资产图片上传失败')
  } finally {
    uploadingImage.value = false
  }
}

function captureImageDimensions(event: Event) {
  const image = event.currentTarget as HTMLImageElement
  loadedImageWidth.value = image.naturalWidth
  loadedImageHeight.value = image.naturalHeight
  if (imageMetadata.value.width === image.naturalWidth && imageMetadata.value.height === image.naturalHeight) return
  void store.updateAssetImageMetadata(asset.value.id, {
    width: image.naturalWidth,
    height: image.naturalHeight,
  })
}

async function saveAnnotations(next: ImageAnnotation[]) {
  await store.saveAssetImageAnnotations(asset.value.id, next)
  annotationOpen.value = false
}

async function downloadImage() {
  if (!asset.value.main_image || downloadingImage.value) return
  downloadingImage.value = true
  try {
    await downloadFile(asset.value.main_image, imageDownloadFilename.value)
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '资产图片下载失败')
  } finally {
    downloadingImage.value = false
  }
}

function chooseDigitalHuman(item: DigitalHuman) {
  config.value.digitalHumanAssetId = item.asset_id
  config.value.digitalHumanPreviewUrl = item.image_url
  digitalHumanPickerOpen.value = false
  void save()
}
</script>

<template>
  <div class="workbench-node-component">
    <WorkbenchNodeFrame
      v-bind="props"
      :data="{
        ...data,
        kind: 'asset',
        title: nickname || asset.canonical_name,
        status: busy ? 'running' : 'ready',
        floating_header: Boolean(asset.main_image),
      }"
    >
      <template #icon>
        <WorkbenchSelect
          class="workbench-node-frame__icon-select"
          v-model="assetTypeValue"
          :options="assetTypeOptions"
          label="资产类型"
          :fallback-icon="assetTypeIconFor(assetTypeValue)"
          icon-only
        />
      </template>
      <template #title>
        <input
          class="workbench-node-frame__title-input nodrag"
          v-model="nickname"
          aria-label="资产昵称"
          maxlength="80"
          @focusout="save"
          @keydown.enter.prevent="($event.target as HTMLInputElement).blur()"
          @pointerdown.stop
        >
      </template>
      <template v-if="imagePixelSize" #meta>
        <span class="workbench-node-frame__media-size">{{ imagePixelSize }}</span>
      </template>
      <template v-if="asset.main_image" #toolbar-actions>
        <button type="button" aria-label="标注资产图片" title="标注图片" @click="annotationOpen = true">
          <Pencil :size="16" aria-hidden="true" />
        </button>
        <button
          type="button"
          :disabled="downloadingImage"
          :aria-label="`下载图片，保存为 ${imageDownloadFilename}`"
          :title="`下载 · ${imageDownloadFilename}`"
          @click="downloadImage"
        >
          <LoaderCircle v-if="downloadingImage" class="workbench-node-context__loading-icon" :size="16" aria-hidden="true" />
          <Download v-else :size="16" aria-hidden="true" />
        </button>
      </template>
      <div class="workbench-node-content" @focusout="handleNodeFocusOut">
        <img
          v-if="asset.main_image"
          class="workbench-uploaded-image-preview"
          :src="asset.main_image"
          :alt="`${nickname || asset.canonical_name}预览`"
          draggable="false"
          loading="lazy"
          decoding="async"
          @load="captureImageDimensions"
        >
        <div v-else class="workbench-media-placeholder">上传或生成图片后，资产与图片会在同一节点展示</div>
        <label class="workbench-asset-image-upload nodrag" :class="{ 'is-disabled': uploadingImage }">
          <ImageUp :size="14" aria-hidden="true" />
          {{ uploadingImage ? '上传中…' : asset.main_image ? '替换图片' : '上传图片' }}
          <input type="file" accept="image/jpeg,image/png,image/webp,image/gif" :disabled="uploadingImage" aria-label="上传资产图片" @change="replaceImage">
        </label>

        <section class="workbench-asset-generation nodrag" aria-label="资产图片生成">
          <div class="workbench-asset-generation__heading"><strong>图片生成</strong><small>已合并历史生成配置</small></div>
          <section class="workbench-asset-variants" aria-label="资产视觉形态">
            <div class="workbench-asset-variants__row">
              <WorkbenchSelect v-model="selectedVariantValue" :options="variantOptions" label="视觉形态" />
              <AppButton type="button" variant="secondary" size="sm" icon-only aria-label="新增视觉形态" @click="addingVariant = !addingVariant"><Plus :size="14" /></AppButton>
              <AppButton v-if="selectedVariantId" type="button" variant="danger" size="sm" icon-only aria-label="删除当前视觉形态" @click="deleteSelectedVariant"><Trash2 :size="14" /></AppButton>
            </div>
            <form v-if="addingVariant" class="workbench-asset-variants__create" @submit.prevent="createVariant">
              <input v-model="variantName" maxlength="100" :placeholder="personAsset ? '例如：红衣变装' : assetType === AssetTypeEnum.SCENE ? '例如：战后废墟' : '例如：展开形态'" aria-label="新形态名称">
              <AppButton type="submit" variant="primary" size="sm" :loading="creatingVariant" :disabled="!variantName.trim()">保存形态</AppButton>
            </form>
            <small>同一资产可保存人物变装、场景升级或道具形态，并为每种形态生成多张图。本章新建的形态会自动用于本章；也可在分镜中用 @{资产名#形态名} 精确指定。</small>
          </section>
          <section v-if="personAsset" class="workbench-library-reference">
            <div class="workbench-library-reference__heading">
              <div><strong>数字人人物</strong><small>可选 · 作为人物参考传入生图模型</small></div>
            </div>
            <button class="workbench-library-reference__selector" type="button" aria-label="从数字人库选择选择后将占用 1 个参考图片名额" @click="digitalHumanPickerOpen = true">
              <span class="workbench-library-reference__placeholder" :class="{ 'has-preview': config.digitalHumanPreviewUrl }">
                <img
                  v-if="config.digitalHumanPreviewUrl"
                  class="workbench-library-reference__preview"
                  :src="config.digitalHumanPreviewUrl"
                  :alt="`${config.digitalHumanAssetId} 数字人预览`"
                  loading="lazy"
                  decoding="async"
                >
                <ScanFace v-else :size="22" aria-hidden="true" />
              </span>
              <span><strong>{{ config.digitalHumanAssetId || '从数字人库选择' }}</strong><small>选择后将占用 1 个参考图片名额</small></span>
            </button>
          </section>

          <fieldset class="workbench-form workbench-capability-form">
            <legend>生成参数</legend>
            <label class="workbench-field"><span>数量</span><input v-model.number="config.generationCount" type="number" min="1" max="4" step="1" aria-label="数量"></label>
            <label class="workbench-field">
              <span>尺寸</span>
              <WorkbenchSuggestedInput
                :model-value="config.size"
                :suggestions="sizeSuggestions"
                label="尺寸"
                inputmode="numeric"
                placeholder="1424x800"
                pattern="\d{2,5}x\d{2,5}"
                @update:model-value="updateSize"
              />
              <small>推荐使用 1K；2K 生成成本约为 1K 的 2 倍。也可输入自定义宽高，如 1280x960。</small>
            </label>
            <label class="workbench-field"><span>格式</span><select v-model="config.format" aria-label="格式"><option value="PNG">PNG</option></select></label>
          </fieldset>
        </section>

        <div v-if="secondaryCandidates.length" class="workbench-candidates" aria-label="图片候选">
          <figure v-for="(candidate, index) in secondaryCandidates" :key="candidate.url">
            <img :src="candidate.url" :alt="`候选图片 ${index + 1}`" loading="lazy" decoding="async">
            <figcaption v-if="candidate.label">{{ candidate.label }}</figcaption>
            <button type="button" :aria-label="candidate.isMain ? `候选图片 ${index + 1} 当前为主图` : `设候选图片 ${index + 1}为主图`" :aria-pressed="candidate.isMain" :disabled="candidate.isMain || changingMainImage" @click="setMainImage(candidate.url)">
              {{ candidate.isMain ? '当前主图' : '设为主图' }}
            </button>
          </figure>
        </div>
      </div>
    </WorkbenchNodeFrame>

    <WorkbenchPromptEditorPanel
      v-if="promptEditorConfig"
      :open="promptEditorOpen"
      :node-key="props.id"
      :config="promptEditorConfig"
      :model-value="description"
      :materials="materialOptions"
      :mentions="materialMentions"
      @update:model-value="description = $event"
      @add="addMaterialReference"
      @close="promptEditor?.close(props.id)"
      @focus-reference="promptEditor?.focusReference($event)"
      @remove-reference="promptEditor?.removeReference($event)"
      @focusout="handlePromptFocusOut"
    />

    <MediaLibraryPicker
      :open="digitalHumanPickerOpen"
      kind="digital-human"
      :selected-asset-id="config.digitalHumanAssetId"
      @close="digitalHumanPickerOpen = false"
      @choose="chooseDigitalHuman($event as DigitalHuman)"
    />
    <ImageAnnotationDialog
      :open="annotationOpen"
      :image-url="asset.main_image || ''"
      :model-value="annotations"
      @close="annotationOpen = false"
      @save="saveAnnotations"
    />
  </div>
</template>

<style scoped>
.workbench-asset-generation {
  display: grid;
  gap: 9px;
  padding-top: 10px;
  border-top: 1px solid #37322e;
}

.workbench-asset-generation__heading,
.workbench-library-reference__heading,
.workbench-library-reference__selector {
  display: flex;
  align-items: center;
  gap: 10px;
}

.workbench-asset-generation__heading,
.workbench-library-reference__heading {
  justify-content: space-between;
}

.workbench-asset-generation__heading > small {
  color: #817870;
}

.workbench-asset-variants {
  display: grid;
  gap: 7px;
  padding: 9px;
  border: 1px solid #39342f;
  border-radius: 10px;
  background: #191715;
}

.workbench-asset-variants__row,
.workbench-asset-variants__create {
  display: flex;
  align-items: center;
  gap: 7px;
}

.workbench-asset-variants__row > :first-child {
  min-width: 0;
  flex: 1;
}

.workbench-asset-variants__create input {
  min-width: 0;
  height: 34px;
  flex: 1;
  padding: 0 10px;
  border: 1px solid #48413b;
  border-radius: 8px;
  color: #eee9e4;
  outline: none;
  background: #131210;
}

.workbench-asset-variants > small {
  color: #817870;
  line-height: 1.5;
}

.workbench-library-reference {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid #3f3934;
  border-radius: 12px;
  background: #191715;
}

.workbench-library-reference__heading > div,
.workbench-library-reference__selector > span:last-child {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.workbench-library-reference strong {
  color: #eee7df;
  font-size: 12px;
}

.workbench-library-reference small {
  color: #948b83;
  font-size: 10px;
}

.workbench-library-reference__selector {
  width: 100%;
  padding: 8px;
  border: 1px solid #49413b;
  border-radius: 10px;
  background: #24211e;
  text-align: left;
}

.workbench-library-reference__selector:hover {
  border-color: #8e75d8;
}

.workbench-library-reference__placeholder {
  display: grid;
  overflow: hidden;
  width: 42px;
  height: 42px;
  flex: none;
  place-items: center;
  border-radius: 8px;
  background: #332e2a;
  color: #a88cf4;
}

.workbench-library-reference__placeholder.has-preview {
  background: #191715;
}

.workbench-library-reference__preview {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center top;
}
</style>
