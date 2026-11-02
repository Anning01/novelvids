import { TaskStatusEnum, type Video } from '@/types'
import { isVideoGenerationActive } from './autoEnhancement'

export type SceneGenerationState = 'completed' | 'error' | 'pending'

export interface SceneStatusRailItem {
  sceneId: number
  sequence: number
  state: SceneGenerationState
}

export function resolveSceneGenerationState(video?: Pick<Video, 'status' | 'metadata'>, hasSubmissionError = false): SceneGenerationState {
  if (hasSubmissionError) return 'error'
  if (video && isVideoGenerationActive(video)) return 'pending'
  const followup = video?.metadata?.auto_enhancement as { stage?: string } | undefined
  if (followup && ['failed', 'needs_review', 'needs_confirmation'].includes(followup.stage || '')) return 'error'
  if (video?.status === TaskStatusEnum.COMPLETED) return 'completed'
  if (video?.status === TaskStatusEnum.FAILED || video?.status === TaskStatusEnum.CANCELLED) return 'error'
  return 'pending'
}
