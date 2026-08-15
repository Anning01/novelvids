import { afterEach, describe, expect, it, vi } from 'vitest'
import { VirtualClipPlaybackClock } from './virtualClipPlaybackClock'

describe('VirtualClipPlaybackClock', () => {
  afterEach(() => vi.useRealTimers())

  it('plays an empty clip for its full duration and then advances', () => {
    vi.useFakeTimers()
    const progress: number[] = []
    const ended = vi.fn()
    const clock = new VirtualClipPlaybackClock(value => progress.push(value), ended)

    clock.play({ duration: 2, startTime: 0.5 })
    vi.advanceTimersByTime(1_000)
    expect(progress.at(-1)).toBeCloseTo(1.5, 1)
    expect(ended).not.toHaveBeenCalled()

    vi.advanceTimersByTime(500)
    expect(progress.at(-1)).toBe(2)
    expect(ended).toHaveBeenCalledTimes(1)
    expect(clock.isPlaying).toBe(false)
  })

  it('respects playback rate and can be paused without losing progress', () => {
    vi.useFakeTimers()
    let currentTime = 0
    const ended = vi.fn()
    const clock = new VirtualClipPlaybackClock(value => { currentTime = value }, ended)

    clock.play({ duration: 5, playbackRate: 2 })
    vi.advanceTimersByTime(750)
    clock.pause()

    expect(currentTime).toBeCloseTo(1.5, 1)
    expect(ended).not.toHaveBeenCalled()
    expect(clock.isPlaying).toBe(false)
  })
})
