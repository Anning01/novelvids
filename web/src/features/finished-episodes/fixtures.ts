import type { FinishedVersion } from './api'

export const finishedVersion = (id = 2): FinishedVersion => ({
  id, revision: id, completed_at: '2026-11-04T12:00:00Z',
  duration: 10, width: 640, height: 360, fps: 24,
})
