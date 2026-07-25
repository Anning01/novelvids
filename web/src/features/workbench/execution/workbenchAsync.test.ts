import { expect, it, vi } from 'vitest'
import { pollUntilTerminal, WorkbenchLoadEpoch } from './workbenchAsync'

it('stops polling immediately after abort', async () => {
  const controller = new AbortController()
  const fetchState = vi.fn().mockResolvedValue({ status: 2 })
  controller.abort()

  await expect(pollUntilTerminal(fetchState, {
    signal: controller.signal,
    intervalMs: 1,
    terminalStatuses: new Set([3, 4, 5]),
  })).rejects.toMatchObject({ name: 'AbortError' })
  expect(fetchState).not.toHaveBeenCalled()
})

it('marks an earlier chapter load as stale', () => {
  const epochs = new WorkbenchLoadEpoch()
  const first = epochs.begin()
  const second = epochs.begin()

  expect(epochs.isCurrent(first)).toBe(false)
  expect(epochs.isCurrent(second)).toBe(true)
})

it('aborts while waiting between polling requests', async () => {
  vi.useFakeTimers()
  const controller = new AbortController()
  const fetchState = vi.fn().mockResolvedValue({ status: 2 })
  const polling = pollUntilTerminal(fetchState, {
    signal: controller.signal,
    intervalMs: 1_000,
    terminalStatuses: new Set([3]),
  })
  await Promise.resolve()
  controller.abort()

  await expect(polling).rejects.toMatchObject({ name: 'AbortError' })
  expect(fetchState).toHaveBeenCalledTimes(1)
  vi.useRealTimers()
})
