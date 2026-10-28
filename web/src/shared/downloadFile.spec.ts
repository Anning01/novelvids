import { afterEach, expect, it, vi } from 'vitest'
import { downloadFile } from './downloadFile'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('sends download authentication and does not save a JSON error as a video', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: 401, message: 'Please sign in' }), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  }))
  vi.stubGlobal('fetch', fetcher)
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  await expect(downloadFile('/api/video/exports/1/download', 'episode.mp4', { Authorization: 'Bearer test-token' })).rejects.toThrow('Please sign in')
  expect(fetcher).toHaveBeenCalledWith('/api/video/exports/1/download', { headers: { Authorization: 'Bearer test-token' } })
  expect(click).not.toHaveBeenCalled()
})

it('keeps existing media downloads and releases the temporary blob URL', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response('video bytes', { headers: { 'Content-Type': 'video/mp4' } }))
  vi.stubGlobal('fetch', fetcher)
  const create = vi.fn().mockReturnValue('blob:test')
  const revoke = vi.fn()
  vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: revoke })
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  await downloadFile('/media/old.mp4', 'episode.mp4')
  expect(fetcher).toHaveBeenCalledWith('/media/old.mp4')
  expect(click).toHaveBeenCalledOnce()
  expect(revoke).toHaveBeenCalledExactlyOnceWith('blob:test')
  expect(document.querySelector('a[download="episode.mp4"]')).toBeNull()
})
