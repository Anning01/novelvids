import { TaskStatusEnum, type Scene, type Video } from '@/types'
import { activeVideoIdForScene } from '@/features/workbench/graph/videoVersions'
import { videoCoverUrl, videoDurationSeconds } from '@/features/workbench/graph/videoMedia'

export type ChapterVideoState = 'completed' | 'generating' | 'failed' | 'pending'

export interface ChapterVideoTimelineItem {
  scene: Scene
  video: Video | null
  state: ChapterVideoState
  duration: number
  coverUrl: string
  errorMessage: string
}

const RUNNING_STATUSES = new Set([TaskStatusEnum.PENDING, TaskStatusEnum.PROCESSING, TaskStatusEnum.QUEUED])

function videoErrorMessage(video: Video | undefined) {
  if (!video?.metadata) return ''
  for (const key of ['error_message', 'error', 'message', 'detail']) {
    const value = video.metadata[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return ''
}

export function completedVideoForScene(scene: Scene, videos: readonly Video[]) {
  const completed = videos.filter(video => video.status === TaskStatusEnum.COMPLETED && Boolean(video.url))
  const activeId = activeVideoIdForScene(scene)
  return completed.find(video => video.id === activeId) ?? completed[0] ?? null
}

export function chapterHasCompletedVideo(scenes: readonly Scene[], videosByScene: Record<number, Video[]>) {
  return scenes.some(scene => Boolean(completedVideoForScene(scene, videosByScene[scene.id] || [])))
}

export function buildChapterVideoTimeline(scenes: readonly Scene[], videosByScene: Record<number, Video[]>): ChapterVideoTimelineItem[] {
  return [...scenes]
    .sort((left, right) => left.sequence - right.sequence)
    .map(scene => {
      const records = videosByScene[scene.id] || []
      const completed = completedVideoForScene(scene, records)
      const latest = records[0]
      const state: ChapterVideoState = completed
        ? 'completed'
        : records.some(video => RUNNING_STATUSES.has(video.status))
          ? 'generating'
          : latest && (latest.status === TaskStatusEnum.FAILED || latest.status === TaskStatusEnum.CANCELLED)
            ? 'failed'
            : 'pending'
      const duration = completed ? videoDurationSeconds(completed) : 0
      return {
        scene,
        video: completed,
        state,
        duration: Math.max(0, duration || scene.duration || 0),
        coverUrl: completed ? videoCoverUrl(completed) : '',
        errorMessage: state === 'failed' ? videoErrorMessage(latest) : '',
      }
    })
}
