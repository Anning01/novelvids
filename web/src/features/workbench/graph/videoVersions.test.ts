import { describe, expect, it } from 'vitest'
import type { Scene, Video } from '@/types'
import { TaskStatusEnum } from '@/types'
import { activeVideoForScene, sceneHasRunningVideo, sceneWithActiveVideo } from './videoVersions'

const scene: Scene = {
  id: 10,
  sequence: 1,
  metadata: { source: 'storyboard', workbench: { activeVideoId: 2 } },
  created_at: '',
  updated_at: '',
}

const videos: Video[] = [
  { id: 3, scene_id: 10, model_type: 1, status: TaskStatusEnum.PROCESSING, created_at: '', updated_at: '' },
  { id: 2, scene_id: 10, model_type: 1, status: TaskStatusEnum.COMPLETED, created_at: '', updated_at: '' },
]

describe('video version selection', () => {
  it('uses the persisted active version instead of always rendering the latest result', () => {
    expect(activeVideoForScene(scene, videos)?.id).toBe(2)
    expect(sceneHasRunningVideo(videos)).toBe(true)
  })

  it('updates active version metadata without discarding existing scene metadata', () => {
    expect(sceneWithActiveVideo(scene, 3).metadata).toEqual({
      source: 'storyboard',
      workbench: { activeVideoId: 3 },
    })
  })
})
