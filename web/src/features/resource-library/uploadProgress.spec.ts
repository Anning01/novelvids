import { expect, it, vi } from 'vitest'
import { uploadWithProgress } from '@/api'

it('reports transfer completion while the server is still processing the file', async () => {
  const transport = {
    open: vi.fn(), setRequestHeader: vi.fn(), send: vi.fn(),
    upload: { onload: null as (() => void) | null, onprogress: null },
    onload: null as (() => void) | null, onerror: null, onabort: null,
    status: 200, responseText: '{"code":0}',
  }
  vi.stubGlobal('XMLHttpRequest', class { constructor() { return transport } })
  try {
    const progress = vi.fn()
    const result = uploadWithProgress('/upload', new FormData(), {}, progress)
    let completed = false
    void result.then(() => { completed = true })
    transport.upload.onload?.()
    await Promise.resolve()
    expect(progress).toHaveBeenCalledWith(100)
    expect(completed).toBe(false)
    transport.onload?.()
    expect(await result).toEqual({ status: 200, text: '{"code":0}' })
  } finally { vi.unstubAllGlobals() }
})
