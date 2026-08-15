<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import type { MaterialMention, MaterialMentionOption } from '../components/materialMentionTypes'
import type { ImageAnnotation, WorkbenchNode } from '../types/workbenchTypes'
import { CheckCircle2, Download, ImageUp, Layers3, Library, LoaderCircle, Maximize2, Minimize2, Pencil, Plus, Trash2, X } from 'lucide-vue-next'
import { computed, inject, markRaw, ref, watch } from 'vue'
import type { Asset, DigitalHuman, ImageGenerationModel } from '@/types'
import { AssetTypeEnum } from '@/types'
import { downloadFile } from '@/shared/downloadFile'
import { notice } from '@/shared/notice'
import { estimateImageCost } from '@/shared/modelPricing'
import AssetDefaultImage from '../components/AssetDefaultImage.vue'
import ImageGenerationParameterPanel, { type ImageGenerationParameters } from '@/components/ImageGenerationParameterPanel.vue'
import ImageAnnotationDialog from '../components/ImageAnnotationDialog.vue'
import DigitalHumanGenerationControl from '../components/DigitalHumanGenerationControl.vue'
import MediaGenerationModelSelector from '../components/MediaGenerationModelSelector.vue'
import WorkbenchNodeFrame from '../components/WorkbenchNodeFrame.vue'
import MediaLibraryPicker from '../components/MediaLibraryPicker.vue'
import WorkbenchPromptEditorPanel from '../components/WorkbenchPromptEditorPanel.vue'
import WorkbenchSelect from '../components/WorkbenchSelect.vue'
import ProjectAssetPicker from '../components/ProjectAssetPicker.vue'
import type { ReusableAssetChoice } from '../components/reusableAsset'
import { assetTypeIconFor, assetTypePresentationOptions, editableAssetTypeOptions } from '../components/assetTypePresentation'
import { disambiguateMaterialMentionNames, materialMentionAssetCategory } from '../components/materialMentionTypes'
import { useWorkbenchNodeDimensionSync } from '../composables/useWorkbenchNodeDimensionSync'
import {
  assetImageMediaMetadata,
  assetImageCandidates,
  assetSelectedImageCandidates,
  isReusableAssetPlaceholder,
  normalizeAssetConfig,
  patchAssetImageMediaMetadata,
  patchAssetWorkbenchConfig,
  type AssetWorkbenchConfig,
} from '../config/assetConfig'
import { registerWorkbenchPromptAction } from '../prompt/promptActionRegistry'
import { registerWorkbenchNodeRun } from '../run/nodeRunRegistry'
import { promptEditorFromData, workbenchPromptEditorKey } from '../prompt/promptEditor'
import { balanceMediaGalleryRows, containedAspectRatioSize, mediaAspectRatioCss, mediaGalleryItemWidth } from '../graph/mediaAspectRatio'
import { useWorkbenchStore } from '../store/workbenchStore'

const props = defineProps<NodeProps>()
const store = useWorkbenchStore()
const promptEditor = inject(workbenchPromptEditorKey, null)
const asset = computed(() => props.data.asset as Asset)
const assetType = ref<AssetTypeEnum>(AssetTypeEnum.PERSON)
const assetTypeExplicit = ref(true)
const nickname = ref('')
const description = ref('')
const prompt = ref('')
const config = ref<AssetWorkbenchConfig>(normalizeAssetConfig(asset.value))
const imageModels = computed(() => (props.data.imageModelOptions as ImageGenerationModel[] | undefined) || [])
const imageModelOptions = computed(() => imageModels.value.map(model => ({ value: model.config_id, label: model.name || model.model })))
const selectedImageModel = computed(() => imageModels.value.find(model => model.config_id === config.value.modelConfigId) || null)
const saving = ref(false)
const changingMainImage = ref(false)
const uploadingImage = ref(false)
const downloadingImage = ref(false)
const downloadingGalleryImageKey = ref('')
const annotationOpen = ref(false)
const imageGalleryExpanded = ref(false)
const loadedImageWidth = ref(0)
const loadedImageHeight = ref(0)
const loadedGalleryImageSizes = ref<Record<string, { width: number; height: number }>>({})
const digitalHumanPickerOpen = ref(false)
const imageFileInput = ref<HTMLInputElement | null>(null)
const variantToolbarOpen = ref(false)
const reusableAssetPickerOpen = ref(false)
const selectedVariantValue = ref('base')
const addingVariant = ref(false)
const variantName = ref('')
const creatingVariant = ref(false)
const reusablePlaceholder = computed(() => isReusableAssetPlaceholder(asset.value))

watch(asset, value => {
  assetType.value = value.asset_type
  const media = assetImageMediaMetadata(value)
  assetTypeExplicit.value = media.source !== 'upload' || media.assetTypeExplicit === true
  nickname.value = value.canonical_name
  description.value = value.description || ''
  prompt.value = value.base_traits || ''
  config.value = normalizeAssetConfig(value)
  if (!imageModelOptions.value.some(option => option.value === config.value.modelConfigId)) {
    config.value.modelConfigId = imageModelOptions.value[0]?.value ?? null
  }
  if (
    selectedVariantValue.value !== 'base'
    && !value.variants?.some(variant => String(variant.id) === selectedVariantValue.value)
  ) selectedVariantValue.value = 'base'
}, { immediate: true })

watch(imageModelOptions, options => {
  if (!options.some(option => option.value === config.value.modelConfigId)) {
    config.value.modelConfigId = options[0]?.value ?? null
  }
}, { immediate: true })

const busy = computed(() => store.busyAssetIds.includes(asset.value.id))
const promptEditorConfig = computed(() => promptEditorFromData(props.data.prompt_editor))
const promptEditorOpen = computed(() => props.data.prompt_editor_open === true && Boolean(promptEditorConfig.value))
const imageMetadata = computed(() => assetImageMediaMetadata(asset.value))
const assetName = computed(() => nickname.value.trim() || asset.value.canonical_name)
const persistedAssetImages = computed(() => assetImageCandidates(asset.value))
const selectedDigitalHumanImage = computed(() => {
  const url = config.value.digitalHumanPreviewUrl
  if (!url) return null
  const persisted = persistedAssetImages.value.find(image => image.url === url)
  return persisted || {
    key: `digital-human:${config.value.digitalHumanAssetId || url}`,
    url,
    isMain: url === asset.value.main_image,
    displayIndex: persistedAssetImages.value.length,
    label: '数字人',
    source: 'digital_human' as const,
  }
})
const assetImages = computed(() => {
  const human = selectedDigitalHumanImage.value
  const values = human && !persistedAssetImages.value.some(image => image.url === human.url)
    ? [...persistedAssetImages.value, human]
    : persistedAssetImages.value
  return values.map((image, displayIndex) => ({
    ...image,
    displayIndex,
    isMain: image.url === asset.value.main_image,
  }))
})
const primaryImage = computed(() => (
  assetImages.value.find(image => image.isMain)
  || assetImages.value[0]
  || null
))
const hasImagePreview = computed(() => Boolean(asset.value.main_image))
const hasMultipleImages = computed(() => assetImages.value.length > 1)
const stackedAssetImages = computed(() => assetImages.value.filter(image => image.key !== primaryImage.value?.key))
const assetImageStackDepth = computed(() => stackedAssetImages.value.length)
const assetImageStageStyle = computed(() => {
  const stackOffset = assetImageStackDepth.value * 4
  return stackOffset
    ? { marginRight: `${stackOffset}px` }
    : undefined
})
const showDefaultVisualImage = computed(() => !hasImagePreview.value)
const defaultVisualImageStyle = computed(() => ({
  aspectRatio: mediaAspectRatioCss(config.value.aspectRatio),
}))
const annotations = computed(() => imageMetadata.value.annotations || [])
const imagePixelSize = computed(() => {
  const width = imageMetadata.value.width || loadedImageWidth.value
  const height = imageMetadata.value.height || loadedImageHeight.value
  return width > 0 && height > 0 ? `${Math.round(width)} × ${Math.round(height)}` : ''
})
function assetImageAspectRatio(image: { key: string; url: string } | null | undefined) {
  if (!image) return config.value.aspectRatio
  const loaded = loadedGalleryImageSizes.value[image.key]
  if (loaded?.width && loaded.height) return `${loaded.width}:${loaded.height}`
  if (image.key === primaryImage.value?.key) {
    const width = imageMetadata.value.width || loadedImageWidth.value
    const height = imageMetadata.value.height || loadedImageHeight.value
    if (width > 0 && height > 0) return `${width}:${height}`
  }
  return config.value.aspectRatio
}
const primaryImageAspectRatio = computed(() => assetImageAspectRatio(primaryImage.value))
function assetGalleryItemStyle(image: { key: string; url: string }) {
  const ratio = assetImageAspectRatio(image)
  return {
    '--workbench-asset-image-aspect-ratio': mediaAspectRatioCss(ratio),
    '--workbench-asset-gallery-item-width': `${mediaGalleryItemWidth(ratio)}px`,
  }
}
const assetGalleryRows = computed(() => balanceMediaGalleryRows(
  assetImages.value,
  assetImageAspectRatio,
  { targetRowWidth: 1280, maxItemsPerRow: 4 },
))
const assetGalleryLayoutSignature = computed(() => assetImages.value
  .map(image => `${image.key}:${assetImageAspectRatio(image)}`)
  .join('|'))
useWorkbenchNodeDimensionSync(props.id, () => `${imageGalleryExpanded.value}:${assetGalleryLayoutSignature.value}`)
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
const assetTypeLabel = computed(() => assetTypePresentationOptions.find(option => option.value === String(assetType.value))?.label || '资产')
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
  if (node.kind === 'asset') {
    const referenceAsset = node.data.asset as Asset | undefined
    return referenceAsset ? assetSelectedImageCandidates(referenceAsset).at(0)?.url || '' : ''
  }
  if (node.kind === 'digital_human') return (node.data.resource as { image_url?: string } | undefined)?.image_url || ''
  return typeof node.data.url === 'string' ? node.data.url : ''
}
const materialOptions = computed<MaterialMentionOption[]>(() => disambiguateMaterialMentionNames(
  referenceEdges.value.flatMap((edge) => {
    const source = store.nodeByKey(edge.source)
    if (!source) return []
    const previewUrl = assetReferencePreview(source)
    const base = {
      nodeKey: source.key,
      name: source.title.trim() || source.key,
      sourceName: source.title.trim() || source.key,
      prompt: '',
      previewUrl,
      hasImage: Boolean(previewUrl),
      mediaKind: 'image' as const,
      assetCategory: source.kind === 'asset'
        ? materialMentionAssetCategory((source.data.asset as Asset | undefined)?.asset_type)
        : source.kind === 'digital_human' ? 'person' as const : undefined,
    }
    if (source.kind !== 'asset') return [base]
    const selectedImages = assetSelectedImageCandidates(source.data.asset as Asset)
    if (selectedImages.length <= 1) return [base]
    return selectedImages.map(image => ({
      ...base,
      mentionKey: `${source.key}:image:${image.displayIndex}`,
      name: `${base.name}-图${image.displayIndex + 1}`,
      previewUrl: image.url,
      hasImage: true,
    }))
  }),
))
const materialMentions = computed<MaterialMention[]>(() => {
  return referenceEdges.value.flatMap((edge) => {
    return materialOptions.value
      .filter(option => option.nodeKey === edge.source)
      .map((option, index) => ({
        ...option,
        edgeKey: `${edge.key}:${option.mentionKey || index}`,
        connectionKey: edge.key,
        mode: 'reference_image' as const,
      }))
  })
})
const personAsset = computed(() => assetType.value === AssetTypeEnum.PERSON)
const backendCanGenerate = computed(() => props.data.generate_capability === true)
const generatorSupportsType = computed(() => ![AssetTypeEnum.PRODUCT, AssetTypeEnum.STYLE].includes(assetType.value))
const canGenerate = computed(() => backendCanGenerate.value && generatorSupportsType.value && config.value.modelConfigId !== null && !busy.value && !saving.value)
const assetTypeOptions = editableAssetTypeOptions
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
const imageParameterValue = computed<ImageGenerationParameters>({
  get: () => ({
    clarity: config.value.clarity,
    aspectRatio: config.value.aspectRatio,
    outputFormat: config.value.outputFormat,
    generationCount: config.value.generationCount,
  }),
  set: value => {
    config.value = {
      ...config.value,
      clarity: value.clarity,
      resolution: value.clarity,
      aspectRatio: value.aspectRatio,
      size: value.aspectRatio,
      outputFormat: value.outputFormat,
      format: value.outputFormat.toUpperCase(),
      generationCount: value.generationCount as AssetWorkbenchConfig['generationCount'],
    }
  },
})

function normalizedDraftConfig(): AssetWorkbenchConfig {
  return {
    ...config.value,
    resolution: config.value.clarity,
    size: config.value.aspectRatio,
    format: config.value.outputFormat.toUpperCase(),
    digitalHumanAssetId: personAsset.value ? config.value.digitalHumanAssetId : '',
    digitalHumanPreviewUrl: personAsset.value ? config.value.digitalHumanPreviewUrl : '',
  }
}

watch(selectedImageModel, model => {
  if (!model) return
  const current = imageParameterValue.value
  const capabilities = model.capabilities
  imageParameterValue.value = {
    clarity: capabilities.clarities.includes(current.clarity) ? current.clarity : capabilities.default_clarity,
    aspectRatio: capabilities.aspect_ratios.includes(current.aspectRatio) ? current.aspectRatio : capabilities.default_aspect_ratio,
    outputFormat: capabilities.output_formats.includes(current.outputFormat) ? current.outputFormat : capabilities.default_output_format,
    generationCount: capabilities.generation_counts.includes(current.generationCount) ? current.generationCount : capabilities.default_generation_count,
  }
}, { immediate: true })

async function save() {
  saving.value = true
  try {
    const nextConfig = normalizedDraftConfig()
    config.value = nextConfig
    await store.saveAsset(asset.value.id, {
      asset_type: assetType.value,
      canonical_name: nickname.value.trim() || asset.value.canonical_name,
      description: description.value,
      base_traits: prompt.value,
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
      base_traits: prompt.value,
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
  cost: computed(() => estimateImageCost(
    selectedImageModel.value?.pricing,
    imageParameterValue.value.clarity,
    imageParameterValue.value.generationCount,
  )),
  controls: [
    {
      id: 'asset-image-generation-model',
      component: markRaw(MediaGenerationModelSelector),
      props: computed(() => ({
        options: imageModelOptions.value,
        label: '图片模型',
      })),
      modelValue: computed(() => config.value.modelConfigId),
      updateModelValue(value) {
        const modelConfigId = Number(value)
        if (Number.isFinite(modelConfigId)) config.value.modelConfigId = modelConfigId
      },
    },
    {
      id: 'asset-image-generation-parameters',
      component: markRaw(ImageGenerationParameterPanel),
      props: computed(() => ({
        capabilities: selectedImageModel.value?.capabilities,
        compact: true,
      })),
      modelValue: imageParameterValue,
      updateModelValue(value) {
        if (value && typeof value === 'object' && !Array.isArray(value)) {
          imageParameterValue.value = value as ImageGenerationParameters
        }
      },
    },
    {
      id: 'asset-image-generation-digital-human',
      component: markRaw(DigitalHumanGenerationControl),
      visible: personAsset,
      props: computed(() => ({
        title: config.value.digitalHumanAssetId || '选择数字人',
        previewUrl: config.value.digitalHumanPreviewUrl,
        selected: Boolean(config.value.digitalHumanAssetId),
      })),
      modelValue: computed(() => ({
        assetId: config.value.digitalHumanAssetId,
        previewUrl: config.value.digitalHumanPreviewUrl,
      })),
      updateModelValue() {},
      events: {
        open: () => { digitalHumanPickerOpen.value = true },
        clear: () => { void clearDigitalHuman() },
      },
    },
  ],
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
  prompt.value = nextPrompt
}

async function setMainImage(url: string) {
  imageGalleryExpanded.value = false
  if (changingMainImage.value || url === asset.value.main_image) return
  changingMainImage.value = true
  try {
    await store.setAssetMainImage(asset.value.id, url)
  } finally {
    changingMainImage.value = false
  }
}

function imageIsPrimary(image: { url: string }) {
  return image.url === primaryImage.value?.url
}

function imageRoleLabel(image: { key: string; url: string }) {
  if (imageIsPrimary(image)) return '主图'
  const referenceIndex = assetImages.value
    .filter(candidate => !imageIsPrimary(candidate))
    .findIndex(candidate => candidate.key === image.key)
  return `参考图 ${Math.max(0, referenceIndex) + 1}`
}

function assetImageStackLayerStyle(image: { key: string; url: string }, layerIndex: number) {
  const xOffset = layerIndex * 4
  return {
    ...containedAspectRatioSize(assetImageAspectRatio(image), primaryImageAspectRatio.value),
    transform: `translateX(${xOffset}px)`,
    transformOrigin: 'top left',
    zIndex: -layerIndex,
  }
}

function captureGalleryImageSize(image: { key: string }, event: Event) {
  const element = event.currentTarget as HTMLImageElement
  if (!element.naturalWidth || !element.naturalHeight) return
  loadedGalleryImageSizes.value = {
    ...loadedGalleryImageSizes.value,
    [image.key]: { width: element.naturalWidth, height: element.naturalHeight },
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

async function downloadGalleryImage(image: { key: string; url: string }) {
  if (downloadingGalleryImageKey.value) return
  downloadingGalleryImageKey.value = image.key
  const extension = image.url.match(/\.([a-z0-9]{2,5})(?:[?#]|$)/i)?.[1]?.toLowerCase() || 'png'
  const safeName = `${assetName.value} · ${imageRoleLabel(image)}`.replace(/[\\/:*?"<>|]+/g, '-')
  try {
    await downloadFile(image.url, `${safeName}.${extension}`)
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '图片下载失败')
  } finally {
    downloadingGalleryImageKey.value = ''
  }
}

async function chooseDigitalHuman(item: DigitalHuman) {
  const previousPreviewUrl = config.value.digitalHumanPreviewUrl
  const wasPrimary = Boolean(previousPreviewUrl && asset.value.main_image === previousPreviewUrl)
  config.value.digitalHumanAssetId = item.asset_id
  config.value.digitalHumanPreviewUrl = item.image_url
  digitalHumanPickerOpen.value = false
  await save()
  if (wasPrimary) await setMainImage(item.image_url)
}

async function clearDigitalHuman() {
  const previousPreviewUrl = config.value.digitalHumanPreviewUrl
  const wasPrimary = Boolean(previousPreviewUrl && asset.value.main_image === previousPreviewUrl)
  const generated = persistedAssetImages.value.find(image => image.url !== previousPreviewUrl)
  config.value.digitalHumanAssetId = ''
  config.value.digitalHumanPreviewUrl = ''
  await save()
  if (wasPrimary) {
    if (generated) await setMainImage(generated.url)
    else await store.setAssetMainImage(asset.value.id, null)
  }
}

async function chooseReusableAsset(choice: ReusableAssetChoice) {
  try {
    if (choice.scope === 'project') {
      await store.reuseProjectAssetInPlaceholder(asset.value.id, choice.asset)
    } else if ('digitalHuman' in choice) {
      await store.applyPublicDigitalHumanToPlaceholder(asset.value.id, choice.digitalHuman)
    } else {
      await store.applyPublicAssetToPlaceholder(asset.value.id, choice.asset)
    }
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '资产复用失败')
  }
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
        body_flush: hasImagePreview || showDefaultVisualImage,
        body_draggable: true,
        floating_header: hasImagePreview || showDefaultVisualImage,
        borderless_media: hasImagePreview || showDefaultVisualImage,
      }"
    >
      <template #icon>
        <WorkbenchSelect
          class="workbench-node-frame__icon-select"
          :class="{ 'is-placeholder-asset-type': reusablePlaceholder }"
          v-model="assetTypeValue"
          :options="assetTypeOptions"
          label="资产类型"
          placeholder="选择资产类型"
          title="选择资产类型"
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
      <template #toolbar-actions>
        <button
          v-if="reusablePlaceholder"
          type="button"
          aria-label="选择可复用资产"
          title="从公共资产或项目资产选择"
          @click="reusableAssetPickerOpen = true"
        >
          <Library :size="16" aria-hidden="true" />
        </button>
        <button
          type="button"
          :disabled="uploadingImage"
          :aria-label="asset.main_image ? '替换资产图片' : '上传资产图片'"
          :title="asset.main_image ? '替换图片' : '上传图片'"
          @click="imageFileInput?.click()"
        >
          <LoaderCircle v-if="uploadingImage" class="workbench-node-context__loading-icon" :size="16" aria-hidden="true" />
          <ImageUp v-else :size="16" aria-hidden="true" />
        </button>
        <input ref="imageFileInput" class="workbench-visually-hidden" type="file" accept="image/jpeg,image/png,image/webp,image/gif" :disabled="uploadingImage" aria-label="上传资产图片" @change="replaceImage">
        <button
          type="button"
          aria-label="管理衍生形态"
          title="衍生形态"
          :class="{ 'is-active': variantToolbarOpen }"
          @click="variantToolbarOpen = !variantToolbarOpen"
        >
          <Layers3 :size="16" aria-hidden="true" />
        </button>
        <button v-if="asset.main_image" type="button" aria-label="标注资产图片" title="标注图片" @click="annotationOpen = true">
          <Pencil :size="16" aria-hidden="true" />
        </button>
        <button
          v-if="asset.main_image"
          type="button"
          :disabled="downloadingImage"
          :aria-label="`下载图片，保存为 ${imageDownloadFilename}`"
          :title="`下载 · ${imageDownloadFilename}`"
          @click="downloadImage"
        >
          <LoaderCircle v-if="downloadingImage" class="workbench-node-context__loading-icon" :size="16" aria-hidden="true" />
          <Download v-else :size="16" aria-hidden="true" />
        </button>
        <section v-if="variantToolbarOpen" class="workbench-node-context__popover workbench-asset-variant-popover" role="dialog" aria-label="衍生形态管理">
          <header>
            <strong>衍生形态</strong>
            <button type="button" aria-label="关闭衍生形态管理" @click="variantToolbarOpen = false"><X :size="14" aria-hidden="true" /></button>
          </header>
          <div class="workbench-asset-variant-popover__row">
            <WorkbenchSelect v-model="selectedVariantValue" :options="variantOptions" label="视觉形态" />
            <button type="button" aria-label="新增视觉形态" title="新增形态" @click="addingVariant = !addingVariant"><Plus :size="14" aria-hidden="true" /></button>
            <button v-if="selectedVariantId" type="button" class="is-danger" aria-label="删除当前视觉形态" title="删除当前形态" @click="deleteSelectedVariant"><Trash2 :size="14" aria-hidden="true" /></button>
          </div>
          <form v-if="addingVariant" class="workbench-asset-variant-popover__create" @submit.prevent="createVariant">
            <input v-model="variantName" maxlength="100" :placeholder="personAsset ? '例如：红衣变装' : assetType === AssetTypeEnum.SCENE ? '例如：战后废墟' : '例如：展开形态'" aria-label="新形态名称">
            <button type="submit" :disabled="creatingVariant || !variantName.trim()">{{ creatingVariant ? '保存中…' : '保存' }}</button>
          </form>
          <small>选择当前生成形态，或新增人物变装、场景升级和道具形态。</small>
        </section>
      </template>
      <div class="workbench-node-content" @focusout="handleNodeFocusOut">
        <div
          v-if="hasImagePreview && !imageGalleryExpanded"
          class="workbench-asset-image-stage"
          :class="{ 'is-multi-image': hasMultipleImages }"
          :style="assetImageStageStyle"
        >
          <span
            v-for="(image, layerIndex) in stackedAssetImages"
            :key="image.key"
            class="workbench-asset-image-stack-layer"
            :style="assetImageStackLayerStyle(image, layerIndex + 1)"
            aria-hidden="true"
          ><img :src="image.url" alt="" draggable="false"></span>
          <img
            class="workbench-uploaded-image-preview"
            :src="asset.main_image"
            :alt="`${assetName}预览`"
            draggable="false"
            loading="lazy"
            decoding="async"
            @load="captureImageDimensions"
          >
          <button
            v-if="hasMultipleImages"
            type="button"
            class="workbench-asset-image-count nodrag"
            :aria-expanded="imageGalleryExpanded"
            :aria-label="`展开${assetName}的 ${assetImages.length} 张图片`"
            @pointerdown.stop
            @click.stop="imageGalleryExpanded = true"
          >
            <Maximize2 :size="17" aria-hidden="true" />
            <span>{{ assetImages.length }}张</span>
          </button>
        </div>
        <section
          v-if="hasMultipleImages && imageGalleryExpanded"
          class="workbench-asset-gallery nodrag"
          role="region"
          :aria-label="`${assetName}图片列表`"
          @pointerdown.stop
        >
          <button
            type="button"
            class="workbench-asset-gallery__collapse"
            :aria-label="`收起${assetName}的 ${assetImages.length} 张图片`"
            @pointerdown.stop
            @click.stop="imageGalleryExpanded = false"
          >
            <Minimize2 :size="17" aria-hidden="true" />
            <span>收起</span>
          </button>
          <div v-for="row in assetGalleryRows" :key="row.map(image => image.key).join('|')" class="workbench-media-gallery__row">
            <article
              v-for="image in row"
              :key="image.key"
              class="workbench-asset-gallery__item"
              :class="{ 'is-primary': imageIsPrimary(image) }"
              :style="assetGalleryItemStyle(image)"
              role="button"
              :tabindex="imageIsPrimary(image) ? -1 : 0"
              :aria-label="imageIsPrimary(image) ? `${assetName}主图` : `设${assetName}${imageRoleLabel(image)}为主图`"
              @click="setMainImage(image.url)"
              @keydown.enter.prevent="setMainImage(image.url)"
              @keydown.space.prevent="setMainImage(image.url)"
            >
              <img :src="image.url" :alt="`${assetName}${imageRoleLabel(image)}`" draggable="false" loading="lazy" decoding="async" @load="captureGalleryImageSize(image, $event)">
              <span class="workbench-asset-gallery__label">
                <CheckCircle2 v-if="imageIsPrimary(image)" :size="13" aria-hidden="true" />
                {{ imageRoleLabel(image) }}
              </span>
              <div class="workbench-asset-gallery__actions">
                <button
                  type="button"
                  :disabled="Boolean(downloadingGalleryImageKey)"
                  :aria-label="`下载${imageRoleLabel(image)}`"
                  @click.stop="downloadGalleryImage(image)"
                >
                  <LoaderCircle v-if="downloadingGalleryImageKey === image.key" class="workbench-node-context__loading-icon" :size="15" aria-hidden="true" />
                  <Download v-else :size="15" aria-hidden="true" />
                  <span>下载</span>
                </button>
              </div>
            </article>
          </div>
        </section>
        <AssetDefaultImage
          v-if="showDefaultVisualImage"
          :icon="assetTypeIconFor(assetTypeValue)"
          :preview-url="config.digitalHumanPreviewUrl"
          :preview-label="config.digitalHumanPreviewUrl ? '数字人参考' : undefined"
          :title="assetName"
          :type-label="assetTypeLabel"
          :style="defaultVisualImageStyle"
        />
      </div>
    </WorkbenchNodeFrame>

    <ProjectAssetPicker
      :open="reusableAssetPickerOpen"
      :novel-id="asset.novel_id"
      :asset-type="assetType"
      :excluded-ids="store.assets.map(item => item.id)"
      @close="reusableAssetPickerOpen = false"
      @choose="chooseReusableAsset"
    />

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
.workbench-asset-variant-popover {
  display: grid;
  width: 330px;
  gap: 10px;
  padding: 11px;
}
.workbench-asset-variant-popover > header,
.workbench-asset-variant-popover__row,
.workbench-asset-variant-popover__create {
  display: flex;
  align-items: center;
  gap: 7px;
}
.workbench-asset-variant-popover > header {
  justify-content: space-between;
  color: #eee8e1;
  font-size: 12px;
}
.workbench-asset-variant-popover button {
  display: grid;
  min-width: 32px;
  height: 32px;
  place-items: center;
  border: 1px solid #4a433d;
  border-radius: 8px;
  color: #aaa39c;
  background: #292522;
  cursor: pointer;
}
.workbench-asset-variant-popover button:hover,
.workbench-asset-variant-popover button:focus-visible {
  border-color: #8f76d8;
  color: #eee8e1;
  outline: none;
}
.workbench-asset-variant-popover button.is-danger:hover,
.workbench-asset-variant-popover button.is-danger:focus-visible {
  border-color: #b96666;
  color: #ef9a9a;
}
.workbench-asset-variant-popover button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}
.workbench-asset-variant-popover__row > :first-child,
.workbench-asset-variant-popover__create input {
  min-width: 0;
  flex: 1;
}
.workbench-asset-variant-popover__create input {
  height: 34px;
  padding: 0 9px;
  border: 1px solid #48413b;
  border-radius: 8px;
  color: #eee9e4;
  outline: none;
  background: #131210;
}
.workbench-asset-variant-popover__create button {
  min-width: 58px;
  padding: 0 10px;
}
.workbench-asset-variant-popover > small {
  color: #817870;
  font-size: 10px;
  line-height: 1.45;
}
</style>
