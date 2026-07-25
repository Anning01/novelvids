import type { Scene } from '@/types'

export const SHOT_ASPECT_RATIOS = ['16:9', '9:16', '1:1', '4:3', '3:4'] as const
export const SHOT_RESOLUTIONS = ['480p', '720p', '1080p'] as const

export type ShotAspectRatio = typeof SHOT_ASPECT_RATIOS[number]
export type ShotResolution = typeof SHOT_RESOLUTIONS[number]
export type ShotReferenceMode = 'prompt' | 'image'

export interface ShotProjectDefaults {
  aspectRatio: ShotAspectRatio
  resolution: ShotResolution
}

export interface ShotWorkbenchConfig {
  duration: number
  aspectRatio: ShotAspectRatio
  resolution: ShotResolution
  useLastFrame: boolean
  referenceMode: ShotReferenceMode
  referenceModes: Record<string, ShotReferenceMode>
  firstFrameUrl: string
  lastFrameUrl: string
  activeVideoId: number | null
  modelType: number | null
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function stringValue(value: unknown) {
  return typeof value === 'string' ? value : ''
}

function numberOrNull(value: unknown) {
  const number = Number(value)
  return Number.isFinite(number) && number > 0 ? number : null
}

function referenceModes(value: unknown): Record<string, ShotReferenceMode> {
  return Object.fromEntries(
    Object.entries(recordValue(value))
      .filter((entry): entry is [string, ShotReferenceMode] => entry[1] === 'prompt' || entry[1] === 'image'),
  )
}

export function normalizeShotConfig(scene: Scene, projectDefaults: ShotProjectDefaults): ShotWorkbenchConfig {
  const workbench = recordValue(recordValue(scene.metadata).workbench)
  const rawDuration = scene.duration === undefined || scene.duration === null ? 6 : Number(scene.duration)
  const duration = Math.max(1, Math.min(30, Number.isFinite(rawDuration) ? rawDuration : 6))
  const aspectRatio = SHOT_ASPECT_RATIOS.includes(workbench.aspectRatio as ShotAspectRatio)
    ? workbench.aspectRatio as ShotAspectRatio
    : SHOT_ASPECT_RATIOS.includes(projectDefaults.aspectRatio) ? projectDefaults.aspectRatio : '9:16'
  const resolution = SHOT_RESOLUTIONS.includes(workbench.resolution as ShotResolution)
    ? workbench.resolution as ShotResolution
    : SHOT_RESOLUTIONS.includes(projectDefaults.resolution) ? projectDefaults.resolution : '720p'
  return {
    duration,
    aspectRatio,
    resolution,
    useLastFrame: workbench.useLastFrame === true,
    referenceMode: workbench.referenceMode === 'image' ? 'image' : 'prompt',
    referenceModes: referenceModes(workbench.referenceModes),
    firstFrameUrl: stringValue(workbench.firstFrameUrl),
    lastFrameUrl: stringValue(workbench.lastFrameUrl),
    activeVideoId: numberOrNull(workbench.activeVideoId),
    modelType: numberOrNull(workbench.modelType),
  }
}

export function patchShotWorkbenchConfig(
  metadata: Scene['metadata'],
  config: ShotWorkbenchConfig,
): Record<string, unknown> {
  return {
    ...recordValue(metadata),
    workbench: { ...config },
  }
}

export function shotGenerationOptions(config: ShotWorkbenchConfig) {
  return {
    generation_mode: config.useLastFrame ? 'keyframes' as const : 'reference' as const,
    first_frame_url: config.firstFrameUrl || undefined,
    last_frame_url: config.useLastFrame ? config.lastFrameUrl || undefined : undefined,
  }
}
