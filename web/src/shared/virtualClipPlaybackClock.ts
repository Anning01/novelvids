export interface VirtualClipPlaybackOptions {
  now?: () => number
  setInterval?: (callback: () => void, delay: number) => number
  clearInterval?: (timer: number) => void
  tickIntervalMs?: number
}

interface VirtualClipPlaybackRequest {
  duration: number
  startTime?: number
  playbackRate?: number
}

export class VirtualClipPlaybackClock {
  private readonly now: () => number
  private readonly schedule: (callback: () => void, delay: number) => number
  private readonly cancel: (timer: number) => void
  private readonly tickIntervalMs: number
  private timer: number | null = null
  private duration = 0
  private startTime = 0
  private playbackRate = 1
  private startedAt = 0

  constructor(
    private readonly onProgress: (currentTime: number) => void,
    private readonly onEnded: () => void,
    options: VirtualClipPlaybackOptions = {},
  ) {
    this.now = options.now || (() => Date.now())
    this.schedule = options.setInterval || ((callback, delay) => window.setInterval(callback, delay))
    this.cancel = options.clearInterval || (timer => window.clearInterval(timer))
    this.tickIntervalMs = options.tickIntervalMs || 50
  }

  get isPlaying() {
    return this.timer !== null
  }

  play(request: VirtualClipPlaybackRequest) {
    this.stop()
    this.duration = Math.max(0, Number(request.duration) || 0)
    this.startTime = Math.min(this.duration, Math.max(0, Number(request.startTime) || 0))
    this.playbackRate = Math.max(0.1, Number(request.playbackRate) || 1)
    this.startedAt = this.now()
    this.onProgress(this.startTime)
    if (this.startTime >= this.duration) {
      this.onEnded()
      return
    }
    this.timer = this.schedule(() => this.tick(), this.tickIntervalMs)
  }

  pause() {
    if (this.timer === null) return
    this.tick()
    this.stop()
  }

  stop() {
    if (this.timer === null) return
    this.cancel(this.timer)
    this.timer = null
  }

  private tick() {
    const elapsed = Math.max(0, this.now() - this.startedAt) / 1000 * this.playbackRate
    const currentTime = Math.min(this.duration, this.startTime + elapsed)
    this.onProgress(currentTime)
    if (currentTime < this.duration) return
    this.stop()
    this.onEnded()
  }
}
