import { afterEach, expect, it, vi } from 'vitest'
import { api } from './api'

afterEach(() => {
  vi.unstubAllGlobals()
})

it('loads the workbench capability contract from its dedicated endpoint', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    code: 0,
    message: 'ok',
    data: {
      upload_media: true,
      generate_asset: true,
      generate_video: true,
      apply_watermark: false,
      compose_video: false,
    },
  }), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  const method = (api as unknown as {
    workbenchCapabilities?: () => Promise<unknown>
  }).workbenchCapabilities

  expect(method).toBeTypeOf('function')
  if (!method) return
  await method()

  expect(fetchMock).toHaveBeenCalledWith('/api/workbench/capabilities', {
    headers: { 'Content-Type': 'application/json' },
  })
})

it('patches a chapter name without replacing the chapter', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    code: 0,
    message: 'ok',
    data: {
      id: 2162,
      novel_id: 9,
      number: 2,
      name: '新画布名',
      created_at: '2026-07-25T00:00:00.000Z',
      updated_at: '2026-07-25T00:00:00.000Z',
    },
  }), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  const method = (api as unknown as {
    updateChapter?: (id: number, patch: { name: string }) => Promise<unknown>
  }).updateChapter

  expect(method).toBeTypeOf('function')
  if (!method) return
  await method(2162, { name: '新画布名' })

  expect(fetchMock).toHaveBeenCalledWith('/api/chapter/2162', {
    headers: { 'Content-Type': 'application/json' },
    method: 'PATCH',
    body: JSON.stringify({ name: '新画布名' }),
  })
})
