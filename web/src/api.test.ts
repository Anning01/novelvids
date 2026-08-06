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

it('loads every chapter page instead of truncating projects at 100 chapters', async () => {
  const chapter = (id: number) => ({
    id,
    novel_id: 9,
    number: id,
    name: `第 ${id} 章`,
    created_at: '2026-07-25T00:00:00.000Z',
    updated_at: '2026-07-25T00:00:00.000Z',
  })
  const fetchMock = vi.fn(async (url: string) => {
    const page = Number(new URL(url, 'http://test').searchParams.get('page'))
    const items = page === 1
      ? Array.from({ length: 100 }, (_, index) => chapter(index + 1))
      : page === 2
        ? Array.from({ length: 100 }, (_, index) => chapter(index + 101))
        : Array.from({ length: 5 }, (_, index) => chapter(index + 201))
    return new Response(JSON.stringify({
      code: 0,
      message: 'ok',
      data: { items, pagination: { total: 205, page, page_size: 100, pages: 3 } },
    }), { status: 200 })
  })
  vi.stubGlobal('fetch', fetchMock)

  const response = await api.chapters(9)

  expect(response.data.items).toHaveLength(205)
  expect(response.data.items.at(-1)?.number).toBe(205)
  expect(fetchMock).toHaveBeenCalledTimes(3)
})

it('requests only assets associated with the selected chapter when chapterId is provided', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    code: 0,
    message: 'ok',
    data: { items: [], pagination: { total: 0, page: 1, page_size: 100, pages: 0 } },
  }), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)

  await api.assets(9, 1, 100, 2162)

  expect(fetchMock).toHaveBeenCalledWith(
    '/api/asset?novel_id=9&page=1&page_size=100&chapter_id=2162',
    { headers: { 'Content-Type': 'application/json' } },
  )
})

it('preserves max context characters in configuration create and update requests', async () => {
  const fetchMock = vi.fn().mockImplementation(() => new Response(JSON.stringify({
    code: 0,
    message: 'ok',
    data: {},
  }), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  const payload = { max_context_characters: 120000 }

  await api.createConfig(payload)
  await api.updateConfig(21, payload)

  expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/config', {
    headers: { 'Content-Type': 'application/json' },
    method: 'POST',
    body: JSON.stringify(payload),
  })
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/config/21', {
    headers: { 'Content-Type': 'application/json' },
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
})
