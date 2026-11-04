import type { ClipPatch, StickerClip } from './types'

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value))
const precision = (value: number) => Math.round(value * 10000) / 10000
export const stickerRotation = (angle: number) => Math.round((((angle + 180) % 360 + 360) % 360 - 180) * 100) / 100

export function scaleSticker(clip: StickerClip, value: number): ClipPatch {
  const y = clip.scale_y ?? clip.scale
  if (clip.lock_aspect === false) return { scale: precision(clamp(value, .1, 4)) }
  const factor = clamp(value / clip.scale, Math.max(.1 / clip.scale, .1 / y), Math.min(4 / clip.scale, 4 / y))
  return { scale: precision(clip.scale * factor), scale_y: precision(y * factor) }
}

export function resizeSticker(clip: StickerClip, dx: number, dy: number, width: number, height: number): ClipPatch {
  if (clip.lock_aspect !== false) {
    const factor = 1 + 2 * (dx * width + dy * height) / (width * width + height * height)
    return scaleSticker(clip, clip.scale * factor)
  }
  return { scale: precision(clamp(clip.scale * (1 + 2 * dx / width), .1, 4)),
    scale_y: precision(clamp((clip.scale_y ?? clip.scale) * (1 + 2 * dy / height), .1, 4)) }
}
