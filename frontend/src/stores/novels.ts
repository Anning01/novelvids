import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Novel, NovelDetail, PaginatedResponse } from '@/types'
import { getNovels, getNovel, createNovel, updateNovel, deleteNovel, extractChapters } from '@/api'

export const useNovelStore = defineStore('novels', () => {
  const novels = ref<Novel[]>([])
  const currentNovel = ref<NovelDetail | null>(null)
  const totalNovels = ref(0)
  const currentPage = ref(1)
  const pageSize = ref(20)
  const isLoading = ref(false)

  async function fetchNovels(page: number = 1): Promise<void> {
    isLoading.value = true
    try {
      const response: PaginatedResponse<Novel> = await getNovels(page, pageSize.value)
      novels.value = response.items
      totalNovels.value = response.total
      currentPage.value = response.page
    } finally {
      isLoading.value = false
    }
  }

  async function fetchNovel(id: string): Promise<void> {
    isLoading.value = true
    try {
      currentNovel.value = await getNovel(id)
    } finally {
      isLoading.value = false
    }
  }

  async function addNovel(data: { title: string; content?: string; author?: string }): Promise<Novel> {
    const novel = await createNovel(data)
    novels.value.unshift(novel)
    return novel
  }

  async function editNovel(
    id: string,
    data: { title?: string; content?: string; author?: string }
  ): Promise<Novel> {
    const updated = await updateNovel(id, data)
    const index = novels.value.findIndex((n) => n.id === id)
    if (index !== -1) {
      novels.value[index] = updated
    }
    if (currentNovel.value?.id === id) {
      currentNovel.value = { ...currentNovel.value, ...updated }
    }
    return updated
  }

  async function removeNovel(id: string): Promise<void> {
    await deleteNovel(id)
    novels.value = novels.value.filter((n) => n.id !== id)
  }

  async function processNovel(id: string): Promise<Novel> {
    const updated = await extractChapters(id)
    const index = novels.value.findIndex((n) => n.id === id)
    if (index !== -1) {
      novels.value[index] = updated
    }
    if (currentNovel.value?.id === id) {
      currentNovel.value = { ...currentNovel.value, ...updated }
    }
    return updated
  }

  return {
    novels,
    currentNovel,
    totalNovels,
    currentPage,
    pageSize,
    isLoading,
    fetchNovels,
    fetchNovel,
    addNovel,
    editNovel,
    removeNovel,
    processNovel,
  }
})
