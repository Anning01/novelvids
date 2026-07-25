import type { Asset } from '@/types'
import { AssetTypeEnum } from '@/types'

export interface AssetWorkbenchConfig {
  generationCount: 1 | 2 | 3 | 4
  resolution: '1K' | '2K'
  size: string
  format: 'PNG'
  digitalHumanAssetId: string
}

export interface AssetSizePreset {
  value: string
  resolution: AssetWorkbenchConfig['resolution']
  ratio: string
  dimensions: string
  default?: boolean
}

export interface AssetImageCandidate {
  key: 'main_image' | 'angle_image_1' | 'angle_image_2'
  url: string
  isMain: boolean
}

export const ASSET_SIZE_PRESETS: readonly AssetSizePreset[] = [
  { value: '1024x1024', resolution: '1K', ratio: '1:1', dimensions: '1024×1024' },
  { value: '1152x864', resolution: '1K', ratio: '4:3', dimensions: '1152×864' },
  { value: '864x1152', resolution: '1K', ratio: '3:4', dimensions: '864×1152' },
  { value: '1424x800', resolution: '1K', ratio: '16:9', dimensions: '1424×800', default: true },
  { value: '800x1424', resolution: '1K', ratio: '9:16', dimensions: '800×1424' },
  { value: '1248x832', resolution: '1K', ratio: '3:2', dimensions: '1248×832' },
  { value: '832x1248', resolution: '1K', ratio: '2:3', dimensions: '832×1248' },
  { value: '1568x672', resolution: '1K', ratio: '21:9', dimensions: '1568×672' },
  { value: '2048x2048', resolution: '2K', ratio: '1:1', dimensions: '2048×2048' },
  { value: '2368x1776', resolution: '2K', ratio: '4:3', dimensions: '2368×1776' },
  { value: '1776x2368', resolution: '2K', ratio: '3:4', dimensions: '1776×2368' },
  { value: '2816x1584', resolution: '2K', ratio: '16:9', dimensions: '2816×1584' },
  { value: '1584x2816', resolution: '2K', ratio: '9:16', dimensions: '1584×2816' },
  { value: '2496x1664', resolution: '2K', ratio: '3:2', dimensions: '2496×1664' },
  { value: '1664x2496', resolution: '2K', ratio: '2:3', dimensions: '1664×2496' },
  { value: '3136x1344', resolution: '2K', ratio: '21:9', dimensions: '3136×1344' },
]

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
  generationCount: 1,
  resolution: '1K',
  size: '1424x800',
  format: 'PNG',
  digitalHumanAssetId: '',
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function validSize(value: unknown): value is string {
  if (typeof value !== 'string') return false
  const match = value.trim().match(/^(\d{2,5})x(\d{2,5})$/)
  return Boolean(match && Number(match[1]) >= 64 && Number(match[2]) >= 64)
}

export function normalizeAssetConfig(asset: Asset): AssetWorkbenchConfig {
  const workbench = recordValue(recordValue(asset.metadata).workbench)
  const generationCount = [1, 2, 3, 4].includes(Number(workbench.generationCount))
    ? Number(workbench.generationCount) as AssetWorkbenchConfig['generationCount']
    : DEFAULT_CONFIG.generationCount
  const resolution = workbench.resolution === '2K' || workbench.resolution === '1K'
    ? workbench.resolution
    : DEFAULT_CONFIG.resolution
  return {
    generationCount,
    resolution,
    size: validSize(workbench.size) ? workbench.size.trim() : DEFAULT_CONFIG.size,
    format: workbench.format === 'PNG' ? 'PNG' : DEFAULT_CONFIG.format,
    digitalHumanAssetId: typeof workbench.digitalHumanAssetId === 'string' ? workbench.digitalHumanAssetId : '',
  }
}

export function patchAssetWorkbenchConfig(
  metadata: Asset['metadata'],
  config: AssetWorkbenchConfig,
): Record<string, unknown> {
  return {
    ...recordValue(metadata),
    workbench: { ...config },
  }
}

export function assetImageCandidates(asset: Asset): AssetImageCandidate[] {
  const values: Array<[AssetImageCandidate['key'], string | undefined]> = asset.angle_image_1 || asset.angle_image_2
    ? [
        ['angle_image_1', asset.angle_image_1],
        ['angle_image_2', asset.angle_image_2],
        ['main_image', asset.main_image],
      ]
    : [['main_image', asset.main_image]]
  const seen = new Set<string>()
  return values.flatMap(([key, url]) => {
    if (!url || seen.has(url)) return []
    seen.add(url)
    return [{ key, url, isMain: url === asset.main_image }]
  })
}

export function assetSizeResolution(size: string): AssetWorkbenchConfig['resolution'] {
  const preset = ASSET_SIZE_PRESETS.find(item => item.value === size)
  if (preset) return preset.resolution
  const dimensions = size.match(/^(\d{2,5})x(\d{2,5})$/)
  return dimensions && Math.max(Number(dimensions[1]), Number(dimensions[2])) >= 1800 ? '2K' : '1K'
}
