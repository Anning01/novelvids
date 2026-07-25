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
  fetchState: () => Promise<T>,
  options: {
    signal: AbortSignal
    intervalMs: number
    terminalStatuses: ReadonlySet<number>
  },
): Promise<T> {
  while (true) {
    if (options.signal.aborted) throw abortError()
    const state = await fetchState()
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
}

export function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}
