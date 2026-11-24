import type { VideoGenerationCapabilities } from '@/types'

export function modelDuration(seconds: number, caps: VideoGenerationCapabilities): number {
  const choices = caps.duration_choices
  if (choices?.length) {
    return choices.reduce((best, value) =>
      Math.abs(value - seconds) < Math.abs(best - seconds) ? value : best)
  }
  return Math.max(caps.duration_min, Math.min(caps.duration_max, seconds))
}
