function abortError() {
  return new DOMException('Aborted', 'AbortError')
}

function waitForInterval(signal: AbortSignal, intervalMs: number) {
  if (signal.aborted) return Promise.reject(abortError())
  return new Promise<void>((resolve, reject) => {
    const finish = () => {
      signal.removeEventListener('abort', onAbort)
      resolve()
    }
    const onAbort = () => {
      clearTimeout(timeout)
      signal.removeEventListener('abort', onAbort)
      reject(abortError())
    }
    const timeout = setTimeout(finish, intervalMs)
    signal.addEventListener('abort', onAbort, { once: true })
  })
}

export async function pollUntilTerminal<T extends { status: number }>(
  fetchState: (signal: AbortSignal) => Promise<T>,
  options: {
    signal: AbortSignal
    intervalMs: number
    terminalStatuses: ReadonlySet<number>
    retryOnError?: (error: unknown) => boolean
    onRetry?: (error: unknown) => void
    requestTimeoutMs?: number
  },
): Promise<T> {
  let failures = 0
  while (true) {
    if (options.signal.aborted) throw abortError()
    const request = new AbortController()
    const cancel = () => request.abort(options.signal.reason)
    options.signal.addEventListener('abort', cancel, { once: true })
    const timeout = options.requestTimeoutMs ? setTimeout(() => request.abort(
      new DOMException('Status request timed out', 'TimeoutError')), options.requestTimeoutMs) : undefined
    let state: T | undefined
    let delay = options.intervalMs
    try {
      state = await fetchState(request.signal)
      failures = 0
    } catch (error) {
      if (options.signal.aborted) throw abortError()
      const failure = request.signal.aborted ? request.signal.reason : error
      if (!options.retryOnError?.(failure)) throw failure
      options.onRetry?.(failure)
      delay = Math.min(30_000, options.intervalMs * 2 ** Math.min(failures++, 3))
    } finally {
      clearTimeout(timeout)
      options.signal.removeEventListener('abort', cancel)
    }
    if (!state) { await waitForInterval(options.signal, delay); continue }
    if (options.signal.aborted) throw abortError()
    if (options.terminalStatuses.has(state.status)) return state
    await waitForInterval(options.signal, options.intervalMs)
  }
}

export class WorkbenchLoadEpoch {
  private value = 0

  begin() {
    this.value += 1
    return this.value
  }

  isCurrent(epoch: number) {
    return epoch === this.value
  }

  snapshot() { return this.value }
}

export function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}
