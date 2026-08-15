import { describe, expect, it } from 'vitest'
import { buildChapterVideoTimeline, chapterHasCompletedVideo, completedVideoForScene } from './chapterVideoTimeline'
import { TaskStatusEnum, type Scene, type Video } from '@/types'

function scene(id: number, sequence = id, currentVideoId?: number): Scene {
  return {
    id,
    chapter_id: 1,
    sequence,
    duration: 6,
    metadata: currentVideoId ? { current_video_id: currentVideoId } : {},
    created_at: '',
    updated_at: '',
  }
}

function video(id: number, sceneId: number, status: TaskStatusEnum, url = ''): Video {
  return { id, scene_id: sceneId, model_type: 1, status, url, created_at: '', updated_at: '' }
}

describe('chapterVideoTimeline', () => {
  it('unlocks the video phase when any scene has one playable completed result', () => {
    const scenes = [scene(1), scene(2)]
    const videos = {
      1: [video(11, 1, TaskStatusEnum.FAILED)],
      2: [video(22, 2, TaskStatusEnum.COMPLETED, '/media/22.mp4')],
    }
    expect(chapterHasCompletedVideo(scenes, videos)).toBe(true)
  })

  it('does not treat a completed record without a URL as playable', () => {
    expect(chapterHasCompletedVideo([scene(1)], { 1: [video(11, 1, TaskStatusEnum.COMPLETED)] })).toBe(false)
  })

  it('keeps the selected completed version even when the latest record failed', () => {
    const target = scene(1, 1, 10)
    const records = [
      video(12, 1, TaskStatusEnum.FAILED),
      video(10, 1, TaskStatusEnum.COMPLETED, '/media/10.mp4'),
    ]
    expect(completedVideoForScene(target, records)?.id).toBe(10)
    expect(buildChapterVideoTimeline([target], { 1: records })[0]?.state).toBe('completed')
  })

  it('preserves failed and pending scenes in sequence order', () => {
    const result = buildChapterVideoTimeline([scene(2, 2), scene(1, 1)], {
      1: [video(10, 1, TaskStatusEnum.FAILED)],
    })
    expect(result.map(item => [item.scene.sequence, item.state])).toEqual([[1, 'failed'], [2, 'pending']])
  })
})
