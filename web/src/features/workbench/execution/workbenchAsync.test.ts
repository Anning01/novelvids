import { afterEach, expect, it, vi } from 'vitest'
import { pollUntilTerminal, WorkbenchLoadEpoch } from './workbenchAsync'
afterEach(() => vi.useRealTimers())

it('retries temporary status errors with capped backoff and retains only read requests', async () => {
  vi.useFakeTimers()
  const controller = new AbortController()
  const read = vi.fn().mockRejectedValueOnce(new TypeError('offline')).mockRejectedValueOnce(new TypeError('offline'))
    .mockResolvedValueOnce({ status: 2 }).mockResolvedValueOnce({ status: 3 })
  const retry = vi.fn()
  const result = pollUntilTerminal(read, { signal: controller.signal, intervalMs: 1000,
    terminalStatuses: new Set([3]), retryOnError: error => error instanceof TypeError, onRetry: retry })
  await vi.advanceTimersByTimeAsync(1000)
  expect(read).toHaveBeenCalledTimes(2)
  await vi.advanceTimersByTimeAsync(2000)
  expect(read).toHaveBeenCalledTimes(3)
  await vi.advanceTimersByTimeAsync(1000)
  await expect(result).resolves.toEqual({ status: 3 })
  expect(retry).toHaveBeenCalledTimes(2)
})

it('times out an unresponsive status request, then reconnects without submitting work', async () => {
  vi.useFakeTimers()
  const controller = new AbortController()
  const read = vi.fn().mockImplementationOnce((signal: AbortSignal) => new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('Body read aborted', 'AbortError')), { once: true })
  })).mockResolvedValueOnce({ status: 3 })
  const result = pollUntilTerminal(read, { signal: controller.signal, intervalMs: 1000,
    terminalStatuses: new Set([3]), requestTimeoutMs: 5000,
    retryOnError: error => error instanceof DOMException && error.name === 'TimeoutError' })
  await vi.advanceTimersByTimeAsync(6000)
  await expect(result).resolves.toEqual({ status: 3 })
  expect(read).toHaveBeenCalledTimes(2)
})

it('does not retry permanent errors and cancels a pending network read on leaving the page', async () => {
  const controller = new AbortController()
  const permanent = vi.fn().mockRejectedValue(new Error('not found'))
  await expect(pollUntilTerminal(permanent, { signal: controller.signal, intervalMs: 1000,
    terminalStatuses: new Set([3]), retryOnError: error => error instanceof TypeError })).rejects.toThrow('not found')
  expect(permanent).toHaveBeenCalledOnce()
  const read = vi.fn((signal: AbortSignal) => new Promise<{ status: number }>((_resolve, reject) => {
    signal.addEventListener('abort', () => reject(signal.reason), { once: true })
  }))
  const result = pollUntilTerminal(read, { signal: controller.signal, intervalMs: 1000, terminalStatuses: new Set([3]) })
  controller.abort()
  await expect(result).rejects.toMatchObject({ name: 'AbortError' })
})

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
