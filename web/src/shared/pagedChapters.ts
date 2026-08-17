import { ref } from 'vue'
import { api } from '@/api'
import type { Chapter, PaginationResponse } from '@/types'

export const CHAPTER_PAGE_SIZE = 30

/**
 * 章节分页加载：每页 30 章，滚动触发 loadMore，避免一次性拉取全部章节。
 */
export function usePagedChapters(getNovelId: () => number | undefined) {
  const chapters = ref<Chapter[]>([])
  const total = ref(0)
  const page = ref(0)
  const loading = ref(false)
  const hasMore = ref(true)

  async function loadMore(): Promise<void> {
    if (loading.value || !hasMore.value) return
    const novelId = getNovelId()
    if (!novelId) return
    loading.value = true
    try {
      const next = page.value + 1
      const response: PaginationResponse<Chapter> = await api.chaptersPage(novelId, next, CHAPTER_PAGE_SIZE)
      chapters.value.push(...response.data.items)
      total.value = response.data.pagination.total
      page.value = next
      hasMore.value = page.value < response.data.pagination.pages
    } finally {
      loading.value = false
    }
  }

  function reset(): void {
    chapters.value = []
    total.value = 0
    page.value = 0
    hasMore.value = true
  }

  return { chapters, total, page, loading, hasMore, loadMore, reset }
}
