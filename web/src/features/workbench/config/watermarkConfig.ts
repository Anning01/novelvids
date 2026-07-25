export type WatermarkPreset = 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right' | 'center'

export interface WatermarkConfig {
  resourceUrl: string
  x: number
  y: number
  scale: number
}

export const WATERMARK_PRESETS: ReadonlyArray<{ value: WatermarkPreset; label: string }> = [
  { value: 'top-left', label: '左上角' },
  { value: 'top-right', label: '右上角' },
  { value: 'bottom-left', label: '左下角' },
  { value: 'bottom-right', label: '右下角' },
  { value: 'center', label: '居中' },
]

const PRESET_POSITIONS: Record<WatermarkPreset, Pick<WatermarkConfig, 'x' | 'y'>> = {
  'top-left': { x: 0.14, y: 0.14 },
  'top-right': { x: 0.86, y: 0.14 },
  'bottom-left': { x: 0.14, y: 0.86 },
  'bottom-right': { x: 0.86, y: 0.86 },
  center: { x: 0.5, y: 0.5 },
}

const finiteOr = (value: unknown, fallback: number) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))

export function watermarkPresetConfig(preset: WatermarkPreset): WatermarkConfig {
  return { resourceUrl: '', ...PRESET_POSITIONS[preset], scale: 0.2 }
}

export function normalizeWatermarkConfig(value: Partial<WatermarkConfig> | null | undefined): WatermarkConfig {
  const fallback = watermarkPresetConfig('bottom-right')
  return {
    resourceUrl: typeof value?.resourceUrl === 'string' ? value.resourceUrl : '',
    x: clamp(finiteOr(value?.x, fallback.x), 0, 1),
    y: clamp(finiteOr(value?.y, fallback.y), 0, 1),
    scale: clamp(finiteOr(value?.scale, fallback.scale), 0.05, 1),
  }
}
