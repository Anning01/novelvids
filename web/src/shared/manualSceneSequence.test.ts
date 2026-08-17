import { describe, expect, it } from 'vitest'
import type { Scene } from '@/types'
import { nextManualSceneSequence } from './manualSceneSequence'

const scene = (sequence: number): Scene => ({
  id: sequence,
  chapter_id: 1,
  sequence,
  duration: 6,
  created_at: '',
  updated_at: '',
})

describe('nextManualSceneSequence', () => {
  it('无分镜时返回 1', () => {
    expect(nextManualSceneSequence([])).toBe(1)
  })
  it('返回最大序号 + 1', () => {
    expect(nextManualSceneSequence([scene(1), scene(3), scene(2)])).toBe(4)
  })
})
