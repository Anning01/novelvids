import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Chapter, ChapterDetail, PaginatedResponse } from '@/types'
import { getChapters, getChapter, updateChapter, deleteChapter, createChapter, api as apiClient } from '@/api'

export const useChapterStore = defineStore('chapters', () => {
  const chapters = ref<Chapter[]>([])
  const currentChapter = ref<ChapterDetail | null>(null)
  const totalChapters = ref(0)
  const currentPage = ref(1)
  const pageSize = ref(50)
  const isLoading = ref(false)

  const hasMore = computed(() => chapters.value.length < totalChapters.value)

  async function fetchChapters(novelId: string, page: number = 1, append: boolean = false): Promise<void> {
    if (page === 1) {
      isLoading.value = true
      chapters.value = [] // Reset list on first page load
    }

    try {
      const response: PaginatedResponse<Chapter> = await getChapters(novelId, page, pageSize.value)

      if (append) {
        chapters.value.push(...response.items)
      } else {
        chapters.value = response.items
      }

      totalChapters.value = response.total
      currentPage.value = response.page
    } finally {
      isLoading.value = false
    }
  }

  async function loadMore(novelId: string): Promise<void> {
    if (isLoading.value || !hasMore.value) return

    await fetchChapters(novelId, currentPage.value + 1, true)
  }

  async function fetchChapter(id: string): Promise<void> {
    isLoading.value = true
    try {
      currentChapter.value = await getChapter(id)
    } finally {
      isLoading.value = false
    }
  }

  async function editChapter(
    id: string,
    data: { title?: string; content?: string; number?: number }
  ): Promise<Chapter> {
    const updated = await updateChapter(id, data)
    const index = chapters.value.findIndex((c) => c.id === id)
    if (index !== -1) {
      chapters.value[index] = updated
    }
    if (currentChapter.value?.id === id) {
      currentChapter.value = { ...currentChapter.value, ...updated }
    }
    return updated
  }

  async function reorderChapters(updates: { id: string; number: number }[]): Promise<void> {
    await apiClient.post('/chapters/reorder', updates)
    // Update local state numbers without fetching to keep UI snappy
    updates.forEach((update) => {
      const chapter = chapters.value.find((c) => c.id === update.id)
      if (chapter) {
        chapter.number = update.number
      }
    })
    // Resort local chapters by number
    chapters.value.sort((a, b) => a.number - b.number)
  }

  async function removeChapter(id: string): Promise<void> {
    await deleteChapter(id)
    chapters.value = chapters.value.filter((c) => c.id !== id)
    totalChapters.value = Math.max(0, totalChapters.value - 1)
    if (currentChapter.value?.id === id) {
      currentChapter.value = null
    }
  }

  async function addChapter(
    novelId: string,
    data: { title: string; content?: string; number?: number }
  ): Promise<Chapter> {
    const chapter = await createChapter(novelId, data)
    chapters.value.push(chapter)
    chapters.value.sort((a, b) => a.number - b.number)
    totalChapters.value += 1
    return chapter
  }

  function clearChapters(): void {
    chapters.value = []
    currentChapter.value = null
    totalChapters.value = 0
    currentPage.value = 1
  }

  return {
    chapters,
    currentChapter,
    totalChapters,
    currentPage,
    pageSize,
    isLoading,
    hasMore,
    fetchChapters,
    loadMore,
    fetchChapter,
    addChapter,
    editChapter,
    reorderChapters,
    removeChapter,
    clearChapters,
  }
})
