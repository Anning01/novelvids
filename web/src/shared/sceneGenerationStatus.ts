import { TaskStatusEnum, type Video } from '@/types'

export type SceneGenerationState = 'completed' | 'error' | 'pending'

export interface SceneStatusRailItem {
  sceneId: number
  sequence: number
  state: SceneGenerationState
}

export function resolveSceneGenerationState(video?: Pick<Video, 'status'>): SceneGenerationState {
  if (video?.status === TaskStatusEnum.COMPLETED) return 'completed'
  if (video?.status === TaskStatusEnum.FAILED || video?.status === TaskStatusEnum.CANCELLED) return 'error'
  return 'pending'
}
