import { afterEach, expect, it, vi } from 'vitest'
import { clipApi } from './clipApi'

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

it.each([['session', 15_000], ['start', 30_000]] as const)('%s stops waiting when the server does not respond', async (operation, timeoutMs) => {
  vi.useFakeTimers()
  vi.spyOn(AbortSignal, 'timeout').mockImplementation(delay => {
    const controller = new AbortController()
    setTimeout(() => controller.abort(new DOMException('Timed out', 'TimeoutError')), delay)
    return controller.signal
  })
  const fetch = vi.fn((_input: RequestInfo | URL, options?: RequestInit) => new Promise<Response>((_resolve, reject) => {
    options?.signal?.addEventListener('abort', () => reject(options.signal?.reason), { once: true })
  }))
  vi.stubGlobal('fetch', fetch)
  const rejected = expect(clipApi[operation](21)).rejects.toMatchObject({ name: 'TimeoutError' })
  await vi.advanceTimersByTimeAsync(timeoutMs)
  await rejected
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(AbortSignal.timeout).toHaveBeenCalledWith(timeoutMs)
})
