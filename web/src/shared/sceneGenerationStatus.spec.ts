import { describe, expect, it } from 'vitest'
import { TaskStatusEnum } from '@/types'
import { resolveSceneGenerationState } from './sceneGenerationStatus'

describe('resolveSceneGenerationState', () => {
  it('maps the latest video task to the three storyboard rail states', () => {
    expect(resolveSceneGenerationState({ status: TaskStatusEnum.COMPLETED })).toBe('completed')
    expect(resolveSceneGenerationState({ status: TaskStatusEnum.FAILED })).toBe('error')
    expect(resolveSceneGenerationState({ status: TaskStatusEnum.CANCELLED })).toBe('error')
    expect(resolveSceneGenerationState({ status: TaskStatusEnum.PROCESSING })).toBe('pending')
    expect(resolveSceneGenerationState()).toBe('pending')
    expect(resolveSceneGenerationState(undefined, true)).toBe('error')
    expect(resolveSceneGenerationState({ status: TaskStatusEnum.COMPLETED }, true)).toBe('error')
  })
})
