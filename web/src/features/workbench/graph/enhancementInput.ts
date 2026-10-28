import type { Scene, Video } from '@/types'
import type { ChapterExport } from '@/features/video-export/api'
import type { WorkbenchEdge, WorkbenchNode } from '../types/workbenchTypes'
import { activeVideoForScene } from './videoVersions'
import { videoAspectRatio, videoPixelSize } from './videoMedia'

export function enhancementInput(key: string, nodes: WorkbenchNode[], edges: WorkbenchEdge[]) {
  const edge = edges.find(item => item.target === key && item.targetHandle === 'video-input')
  const source = nodes.find(item => item.key === edge?.source)
  if (!source) return null
  if (source.kind === 'video_enhancement') {
    const result = source.data.enhancement_result as ChapterExport | undefined
    return result?.status === 3 && result.url ? {
      key: `export:${result.id}`, exportId: result.id, videoId: null,
      shortSide: Math.min(result.output_probe.width || 0, result.output_probe.height || 0), title: source.title,
      ratio: `${result.output_probe.width || 16}:${result.output_probe.height || 9}`,
    } : null
  }
  const video = source.kind === 'shot'
    ? activeVideoForScene(source.data.scene as Scene, (source.data.videos || []) as Video[])
    : source.kind === 'video_result' ? source.data.video as Video : null
  if (!video?.url || video.status !== 3) return null
  const size = videoPixelSize(video)
  return { key: `video:${video.id}`, exportId: null, videoId: video.id,
    shortSide: size ? Math.min(size.width, size.height) : 0, title: source.title,
    ratio: size ? `${size.width}:${size.height}` : videoAspectRatio(video) }
}
