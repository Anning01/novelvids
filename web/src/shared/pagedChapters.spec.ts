import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import { usePagedChapters } from './pagedChapters'

vi.mock('@/api', () => ({ api: { chaptersPage: vi.fn(), chapter: vi.fn() } }))
const laterChapter = { id: 81, novel_id: 7, number: 81, name: '后续章节', created_at: '', updated_at: '' }
beforeEach(() => vi.clearAllMocks())

it('restores a routed chapter beyond page one without duplicating it during pagination', async () => {
  vi.mocked(api.chapter).mockResolvedValue({ code: 0, message: '', data: laterChapter })
  const paged = usePagedChapters(() => 7)
  expect(await paged.ensureChapter(81)).toEqual(laterChapter)
  vi.mocked(api.chaptersPage).mockResolvedValue({ code: 0, message: '', data: {
    items: [laterChapter], pagination: { page: 1, total: 81, pages: 3, page_size: 30 },
  } })
  await paged.loadMore()
  expect(paged.chapters.value).toHaveLength(1)
  await paged.ensureChapter(81)
  expect(api.chapter).toHaveBeenCalledOnce()
})

it('never inserts a routed chapter from a different project', async () => {
  vi.mocked(api.chapter).mockResolvedValue({ code: 0, message: '', data: { ...laterChapter, novel_id: 8 } })
  const paged = usePagedChapters(() => 7)
  expect(await paged.ensureChapter(81)).toBeUndefined()
  expect(paged.chapters.value).toEqual([])
})
