import { describe, expect, it } from 'vitest'
import { runVideoGenerationQueue } from './videoGenerationQueue'

describe('runVideoGenerationQueue', () => {
  it('runs strictly in scene order when last-frame continuity is enabled', async () => {
    const started: number[] = []
    const completed: number[] = []
    let active = 0
    let maxActive = 0

    const completedCount = await runVideoGenerationQueue([1, 2, 3], 3, true, async scene => {
      started.push(scene)
      active += 1
      maxActive = Math.max(maxActive, active)
      await Promise.resolve()
      active -= 1
      completed.push(scene)
      return true
    })

    expect(started).toEqual([1, 2, 3])
    expect(completed).toEqual([1, 2, 3])
    expect(maxActive).toBe(1)
    expect(completedCount).toBe(3)
  })

  it('uses model concurrency when continuity is disabled', async () => {
    let active = 0
    let maxActive = 0
    const completedCount = await runVideoGenerationQueue([1, 2, 3], 2, false, async () => {
      active += 1
      maxActive = Math.max(maxActive, active)
      await new Promise(resolve => window.setTimeout(resolve, 5))
      active -= 1
      return true
    })

    expect(maxActive).toBe(2)
    expect(completedCount).toBe(3)
  })
})
