import type { Scene, Video } from '@/types'
import { TaskStatusEnum } from '@/types'

const TERMINAL_VIDEO_STATUSES = new Set([
  TaskStatusEnum.COMPLETED,
  TaskStatusEnum.FAILED,
  TaskStatusEnum.CANCELLED,
])

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

export function activeVideoIdForScene(scene: Scene) {
  const value = recordValue(recordValue(scene.metadata).workbench).activeVideoId
  const id = Number(value)
  return Number.isFinite(id) && id > 0 ? id : null
}

export function activeVideoForScene(scene: Scene, videos: readonly Video[]) {
  const activeId = activeVideoIdForScene(scene)
  return videos.find(video => video.id === activeId) ?? videos[0] ?? null
}

export function sceneHasRunningVideo(videos: readonly Video[]) {
  return videos.some(video => !TERMINAL_VIDEO_STATUSES.has(video.status))
}

export function sceneWithActiveVideo(scene: Scene, videoId: number): Scene {
  const metadata = recordValue(scene.metadata)
  return {
    ...scene,
    metadata: {
      ...metadata,
      workbench: {
        ...recordValue(metadata.workbench),
        activeVideoId: videoId,
      },
    },
  }
}

export function isTerminalVideo(video: Video) {
  return TERMINAL_VIDEO_STATUSES.has(video.status)
}
