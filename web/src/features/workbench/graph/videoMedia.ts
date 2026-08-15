import type { Video } from '@/types'

function metadata(video: Video) {
  return video.metadata || {}
}

function stringValue(video: Video, ...keys: string[]) {
  const values = metadata(video)
  for (const key of keys) {
    const value = values[key]
    if (typeof value === 'string' && value.trim()) return value
  }
  return ''
}

function numberValue(video: Video, ...keys: string[]) {
  const values = metadata(video)
  for (const key of keys) {
    const value = values[key]
    if (typeof value === 'number' && Number.isFinite(value)) return value
    if (typeof value === 'string' && value.trim() && Number.isFinite(Number(value))) return Number(value)
  }
  return 0
}

export function videoCoverUrl(video: Video) {
  return stringValue(video, 'cover_url', 'coverUrl', 'poster_url', 'posterUrl', 'first_frame_url', 'firstFrameUrl')
}

export function videoAspectRatio(video: Video) {
  const configured = stringValue(video, 'ratio', 'aspect_ratio', 'aspectRatio')
  if (configured) return configured
  const width = numberValue(video, 'width', 'video_width', 'videoWidth')
  const height = numberValue(video, 'height', 'video_height', 'videoHeight')
  return width > 0 && height > 0 ? `${width}:${height}` : ''
}

export function videoDurationSeconds(video: Video) {
  return numberValue(video, 'duration_seconds', 'durationSeconds', 'duration')
}

export function videoResolution(video: Video) {
  return stringValue(video, 'resolution', 'video_resolution', 'videoResolution')
}

export function videoPixelSize(video: Video) {
  const width = numberValue(video, 'width', 'video_width', 'videoWidth')
  const height = numberValue(video, 'height', 'video_height', 'videoHeight')
  return width > 0 && height > 0 ? { width, height } : null
}

export function videoDownloadFilename(video: Video, title: string) {
  const mimeType = stringValue(video, 'mime_type', 'mimeType')
  const extension = mimeType.includes('webm')
    ? 'webm'
    : mimeType.includes('quicktime')
      ? 'mov'
      : video.url?.match(/\.([a-z0-9]{2,5})(?:[?#]|$)/i)?.[1]?.toLowerCase() || 'mp4'
  const safeTitle = title.trim().replace(/[\\/:*?"<>|]+/g, '-').replace(/\s+/g, ' ') || `video-${video.id}`
  return `${safeTitle}.${extension}`
}
