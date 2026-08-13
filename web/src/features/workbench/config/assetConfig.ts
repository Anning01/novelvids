import type { Asset } from '@/types'
import type { ImageAnnotation } from '../types/workbenchTypes'
import { AssetTypeEnum } from '@/types'

export interface AssetWorkbenchConfig {
  modelConfigId: number | null
  generationCount: 1 | 2 | 4
  clarity: string
  resolution: string
  aspectRatio: string
  size: string
  outputFormat: string
  format: string
  digitalHumanAssetId: string
  digitalHumanPreviewUrl: string
}

export interface AssetImageCandidate {
  key: string
  url: string
  isMain: boolean
  displayIndex: number
  label?: string
  source?: 'asset' | 'digital_human'
}

export interface AssetImageMediaMetadata {
  source?: 'upload' | 'generation'
  assetTypeExplicit?: boolean
  filename?: string
  originalFilename?: string
  mimeType?: string
  width?: number
  height?: number
  annotations?: ImageAnnotation[]
}

export const ASSET_TYPE_OPTIONS = [
  { value: AssetTypeEnum.PERSON, label: '人物' },
  { value: AssetTypeEnum.ITEM, label: '物品' },
  { value: AssetTypeEnum.SCENE, label: '场景' },
  { value: AssetTypeEnum.PRODUCT, label: '商品' },
  { value: AssetTypeEnum.STYLE, label: '风格' },
] as const

export function assetTypeLabel(type: AssetTypeEnum) {
  return ASSET_TYPE_OPTIONS.find(item => item.value === type)?.label || '资产'
}

const DEFAULT_CONFIG: AssetWorkbenchConfig = {
  modelConfigId: null,
  generationCount: 1,
  resolution: '1K',
  clarity: '1K',
  aspectRatio: '16:9',
  size: '1424x800',
  outputFormat: 'png',
  format: 'PNG',
  digitalHumanAssetId: '',
  digitalHumanPreviewUrl: '',
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

export function assetImageMediaMetadata(asset: Asset): AssetImageMediaMetadata {
  const image = recordValue(recordValue(asset.metadata).workbenchImage)
  return {
    source: image.source === 'upload' || image.source === 'generation' ? image.source : undefined,
    assetTypeExplicit: image.assetTypeExplicit === true,
    filename: typeof image.filename === 'string' ? image.filename : undefined,
    originalFilename: typeof image.originalFilename === 'string' ? image.originalFilename : undefined,
    mimeType: typeof image.mimeType === 'string' ? image.mimeType : undefined,
    width: typeof image.width === 'number' && Number.isFinite(image.width) ? image.width : undefined,
    height: typeof image.height === 'number' && Number.isFinite(image.height) ? image.height : undefined,
    annotations: Array.isArray(image.annotations) ? image.annotations as ImageAnnotation[] : [],
  }
}

export function patchAssetImageMediaMetadata(
  metadata: Asset['metadata'],
  patch: Partial<AssetImageMediaMetadata>,
): Record<string, unknown> {
  const current = recordValue(metadata)
  const image = recordValue(current.workbenchImage)
  return {
    ...current,
    workbenchImage: {
      ...image,
      ...patch,
    },
  }
}

function validSize(value: unknown): value is string {
  if (typeof value !== 'string') return false
  const match = value.trim().match(/^(\d{2,5})x(\d{2,5})$/)
  return Boolean(match && Number(match[1]) >= 64 && Number(match[2]) >= 64)
}

export function normalizeAssetConfig(asset: Asset): AssetWorkbenchConfig {
  const metadata = recordValue(asset.metadata)
  const workbench = recordValue(recordValue(asset.metadata).workbench)
  const modelConfigId = Number(metadata.model_config_id ?? workbench.modelConfigId)
  const resolution = typeof workbench.resolution === 'string' ? workbench.resolution : DEFAULT_CONFIG.resolution
  const clarity = typeof workbench.clarity === 'string' ? workbench.clarity : resolution
  const aspectRatio = typeof workbench.aspectRatio === 'string'
    ? workbench.aspectRatio
    : typeof metadata.aspect_ratio === 'string'
      ? metadata.aspect_ratio
      : DEFAULT_CONFIG.aspectRatio
  const outputFormat = typeof workbench.outputFormat === 'string'
    ? workbench.outputFormat.toLowerCase()
    : typeof workbench.format === 'string'
      ? workbench.format.toLowerCase()
      : DEFAULT_CONFIG.outputFormat
  return {
    modelConfigId: Number.isInteger(modelConfigId) && modelConfigId > 0 ? modelConfigId : null,
    generationCount: 1,
    resolution,
    clarity,
    aspectRatio,
    size: validSize(workbench.size) ? workbench.size.trim() : DEFAULT_CONFIG.size,
    outputFormat,
    format: outputFormat.toUpperCase(),
    digitalHumanAssetId: typeof workbench.digitalHumanAssetId === 'string' ? workbench.digitalHumanAssetId : '',
    digitalHumanPreviewUrl: typeof workbench.digitalHumanPreviewUrl === 'string' ? workbench.digitalHumanPreviewUrl : '',
  }
}

export function patchAssetWorkbenchConfig(
  metadata: Asset['metadata'],
  config: AssetWorkbenchConfig,
): Record<string, unknown> {
  const normalizedConfig = { ...config, generationCount: 1 as const }
  return {
    ...recordValue(metadata),
    model_config_id: config.modelConfigId,
    clarity: config.clarity,
    resolution: config.clarity,
    aspect_ratio: config.aspectRatio,
    output_format: config.outputFormat,
    generation_count: 1,
    workbench: normalizedConfig,
  }
}

export function assetImageCandidates(asset: Asset): AssetImageCandidate[] {
  const baseValues: Array<[AssetImageCandidate['key'], string | undefined, string?]> = asset.angle_image_1 || asset.angle_image_2
    ? [
        ['angle_image_1', asset.angle_image_1],
        ['angle_image_2', asset.angle_image_2],
        ['main_image', asset.main_image],
      ]
    : [['main_image', asset.main_image]]
  const gallery = Array.isArray(recordValue(asset.metadata).image_gallery)
    ? recordValue(asset.metadata).image_gallery as unknown[]
    : []
  const values: Array<[string, string | undefined, string?]> = [
    ...baseValues,
    ...gallery.flatMap((url, index) => typeof url === 'string'
      ? [[`gallery-${index}`, url, `生成图 ${index + 1}`] as [string, string, string]]
      : []),
    ...(asset.variants || []).flatMap(variant => variant.images.map((url, index): [string, string, string] => [
      `variant-${variant.id}-${index}`,
      url,
      variant.name,
    ])),
  ]
  const seen = new Set<string>()
  return values.flatMap(([key, url, label]) => {
    if (!url || seen.has(url)) return []
    seen.add(url)
    return [{
      key,
      url,
      ...(label ? { label } : {}),
      isMain: url === asset.main_image,
      displayIndex: seen.size - 1,
      source: 'asset' as const,
    }]
  })
}

export function assetSelectedImageCandidates(asset: Asset): AssetImageCandidate[] {
  const candidates = assetImageCandidates(asset)
  const selectedValue = recordValue(asset.metadata).selected_image_urls
  if (!Array.isArray(selectedValue)) {
    const primary = candidates.find(candidate => candidate.isMain)
    return primary ? [primary] : candidates.slice(0, 1)
  }
  const selected = new Set(selectedValue.filter((value): value is string => typeof value === 'string' && Boolean(value.trim())))
  return candidates.filter(candidate => selected.has(candidate.url.trim()))
}
