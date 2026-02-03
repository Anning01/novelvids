<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getNovels, createNovel, updateNovel, deleteNovel } from '@/api/novels'
import type { Novel } from '@/types'

const { t } = useI18n()
const router = useRouter()

// List state
const novels = ref<Novel[]>([])
const isLoading = ref(true)
const error = ref<string | null>(null)
const currentPage = ref(1)
const totalPages = ref(1)
const totalNovels = ref(0)
const pageSize = 12

// Create modal state
const showCreateModal = ref(false)
const newNovel = ref({ title: '', content: '', author: '' })
const isCreating = ref(false)

// Edit modal state
const showEditModal = ref(false)
const editingNovel = ref<Novel | null>(null)
const editForm = ref({ title: '', author: '' })
const isUpdating = ref(false)

// Upload state
const showUploadModal = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const fileName = ref('')
const filePreview = ref('')
const isUploading = ref(false)
let fullFileContent = ''

// Search
const searchQuery = ref('')

const filteredNovels = computed(() => {
  if (!searchQuery.value) return novels.value
  const query = searchQuery.value.toLowerCase()
  return novels.value.filter(
    (n) =>
      n.title.toLowerCase().includes(query) ||
      (n.author && n.author.toLowerCase().includes(query))
  )
})

async function loadNovels(): Promise<void> {
  isLoading.value = true
  error.value = null
  try {
    const response = await getNovels(currentPage.value, pageSize)
    novels.value = response.items
    totalPages.value = response.totalPages
    totalNovels.value = response.total
  } catch (e) {
    error.value = (e as Error).message || 'Failed to load novels'
  } finally {
    isLoading.value = false
  }
}

async function handleCreate(): Promise<void> {
  if (!newNovel.value.title.trim()) return
  isCreating.value = true
  try {
    const novel = await createNovel({
      title: newNovel.value.title,
      content: newNovel.value.content || undefined,
      author: newNovel.value.author || undefined,
    })
    showCreateModal.value = false
    newNovel.value = { title: '', content: '', author: '' }
    router.push(`/editor/${novel.id}`)
  } catch (e) {
    error.value = (e as Error).message || 'Failed to create novel'
  } finally {
    isCreating.value = false
  }
}

function openEditModal(novel: Novel): void {
  editingNovel.value = novel
  editForm.value = { title: novel.title, author: novel.author || '' }
  showEditModal.value = true
}

async function handleUpdate(): Promise<void> {
  if (!editingNovel.value || !editForm.value.title.trim()) return
  isUpdating.value = true
  try {
    await updateNovel(editingNovel.value.id, {
      title: editForm.value.title,
      author: editForm.value.author || undefined,
    })
    showEditModal.value = false
    editingNovel.value = null
    await loadNovels()
  } catch (e) {
    error.value = (e as Error).message || 'Failed to update novel'
  } finally {
    isUpdating.value = false
  }
}

async function handleDelete(novel: Novel): Promise<void> {
  if (!confirm(`${t('common.confirmDelete')} "${novel.title}"?`)) return
  try {
    await deleteNovel(novel.id)
    await loadNovels()
  } catch (e) {
    error.value = (e as Error).message || 'Failed to delete novel'
  }
}

function openFilePicker(): void {
  fileInput.value?.click()
}

function handleFileChange(e: Event): void {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return

  isUploading.value = true
  fileName.value = file.name

  const reader = new FileReader()
  reader.onload = () => {
    fullFileContent = String(reader.result || '')
    const previewLen = 2000
    filePreview.value =
      fullFileContent.length > previewLen
        ? fullFileContent.slice(0, previewLen) + `\n\n... (${t('novels.totalChars', { count: fullFileContent.length })})`
        : fullFileContent
    isUploading.value = false
    showUploadModal.value = true
  }
  reader.onerror = () => {
    isUploading.value = false
    error.value = 'Failed to read file'
  }
  reader.readAsText(file)
  target.value = ''
}

function confirmUpload(): void {
  newNovel.value.content = fullFileContent
  showUploadModal.value = false
  filePreview.value = ''
  fullFileContent = ''
}

function cancelUpload(): void {
  showUploadModal.value = false
  filePreview.value = ''
  fullFileContent = ''
  fileName.value = ''
}

function closeCreateModal(): void {
  showCreateModal.value = false
  newNovel.value = { title: '', content: '', author: '' }
}

function closeEditModal(): void {
  showEditModal.value = false
  editingNovel.value = null
}

function goToNovel(novel: Novel): void {
  router.push(`/editor/${novel.id}`)
}

function getStatusColor(status: string): string {
  switch (status) {
    case 'completed':
      return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
    case 'processing':
      return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
    case 'failed':
      return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
    default:
      return 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300'
  }
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString()
}

onMounted(() => {
  loadNovels()
})
</script>

<template>
  <div class="novels-view p-6 max-w-7xl mx-auto">
    <!-- Header -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
      <div>
        <h1 class="text-2xl font-bold text-gray-900 dark:text-white">{{ t('novels.title') }}</h1>
        <p class="text-gray-500 dark:text-gray-400 mt-1">{{ t('novels.description') }}</p>
      </div>
      <button type="button" class="btn-primary whitespace-nowrap" @click="showCreateModal = true">
        <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
        </svg>
        {{ t('novels.createNovel') }}
      </button>
    </div>

    <!-- Search Bar -->
    <div class="mb-6">
      <div class="relative">
        <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        <input
          v-model="searchQuery"
          type="text"
          :placeholder="t('novels.searchPlaceholder')"
          class="w-full pl-10 pr-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-primary-500 focus:border-transparent"
        />
      </div>
    </div>

    <!-- Error -->
    <div v-if="error" class="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg text-red-600 dark:bg-red-900/20 dark:border-red-800 dark:text-red-400">
      {{ error }}
      <button type="button" class="ml-2 underline" @click="error = null">{{ t('common.close') }}</button>
    </div>

    <!-- Loading -->
    <div v-if="isLoading" class="flex justify-center py-12">
      <div class="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-primary-500" />
    </div>

    <!-- Empty State -->
    <div v-else-if="filteredNovels.length === 0" class="card p-12 text-center">
      <svg class="w-16 h-16 mx-auto mb-4 text-gray-400 dark:text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
      </svg>
      <p class="text-gray-500 dark:text-gray-400 mb-4">{{ t('novels.empty') }}</p>
      <button type="button" class="btn-primary" @click="showCreateModal = true">
        {{ t('novels.createFirst') }}
      </button>
    </div>

    <!-- Novels Grid -->
    <div v-else class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      <div
        v-for="novel in filteredNovels"
        :key="novel.id"
        class="card overflow-hidden hover:shadow-lg transition-shadow cursor-pointer group"
        @click="goToNovel(novel)"
      >
        <!-- Card Header with gradient -->
        <div class="h-24 bg-gradient-to-br from-primary-500 to-accent-500 relative">
          <div class="absolute inset-0 bg-black/10" />
          <div class="absolute bottom-2 left-3 right-3">
            <span :class="['px-2 py-0.5 text-xs font-medium rounded', getStatusColor(novel.status)]">
              {{ t(`novels.status.${novel.status}`) }}
            </span>
          </div>
        </div>

        <!-- Card Body -->
        <div class="p-4">
          <h3 class="font-semibold text-gray-900 dark:text-white truncate group-hover:text-primary-600 dark:group-hover:text-primary-400 transition-colors">
            {{ novel.title }}
          </h3>
          <p v-if="novel.author" class="text-sm text-gray-500 dark:text-gray-400 mt-1 truncate">
            {{ novel.author }}
          </p>
          <div class="flex items-center gap-4 mt-3 text-sm text-gray-500 dark:text-gray-400">
            <span class="flex items-center gap-1">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              {{ novel.totalChapters }}
            </span>
            <span>{{ formatDate(novel.createdAt) }}</span>
          </div>

          <!-- Actions -->
          <div class="flex justify-end gap-1 mt-3 pt-3 border-t border-gray-100 dark:border-gray-700">
            <button
              type="button"
              class="p-1.5 text-gray-500 hover:text-primary-600 hover:bg-primary-50 dark:hover:bg-primary-900/20 rounded transition-colors"
              :title="t('common.edit')"
              @click.stop="openEditModal(novel)"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
              </svg>
            </button>
            <button
              type="button"
              class="p-1.5 text-gray-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded transition-colors"
              :title="t('common.delete')"
              @click.stop="handleDelete(novel)"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Pagination -->
    <div v-if="totalPages > 1" class="mt-6 flex justify-center items-center gap-2">
      <button
        type="button"
        :disabled="currentPage === 1"
        :class="[
          'px-3 py-1.5 rounded text-sm font-medium transition-colors',
          currentPage === 1
            ? 'bg-gray-100 text-gray-400 cursor-not-allowed dark:bg-gray-700 dark:text-gray-500'
            : 'bg-gray-200 text-gray-700 hover:bg-gray-300 dark:bg-gray-600 dark:text-gray-200 dark:hover:bg-gray-500',
        ]"
        @click="currentPage--; loadNovels()"
      >
        {{ t('common.prev') }}
      </button>
      <span class="px-3 py-1.5 text-sm text-gray-600 dark:text-gray-300">
        {{ currentPage }} / {{ totalPages }}
      </span>
      <button
        type="button"
        :disabled="currentPage >= totalPages"
        :class="[
          'px-3 py-1.5 rounded text-sm font-medium transition-colors',
          currentPage >= totalPages
            ? 'bg-gray-100 text-gray-400 cursor-not-allowed dark:bg-gray-700 dark:text-gray-500'
            : 'bg-gray-200 text-gray-700 hover:bg-gray-300 dark:bg-gray-600 dark:text-gray-200 dark:hover:bg-gray-500',
        ]"
        @click="currentPage++; loadNovels()"
      >
        {{ t('common.next') }}
      </button>
    </div>

    <!-- Total Count -->
    <div class="mt-4 text-center text-sm text-gray-500 dark:text-gray-400">
      {{ t('common.total') }}: {{ totalNovels }}
    </div>

    <!-- Hidden file input -->
    <input
      ref="fileInput"
      type="file"
      accept=".txt,.md"
      class="hidden"
      @change="handleFileChange"
    />

    <!-- Create Modal -->
    <Teleport to="body">
      <div v-if="showCreateModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50" @click.self="closeCreateModal">
        <div class="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
          <div class="p-6">
            <h2 class="text-xl font-semibold text-gray-900 dark:text-white mb-4">{{ t('novels.createNovel') }}</h2>

            <div class="space-y-4">
              <div>
                <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  {{ t('novels.novelTitle') }} <span class="text-red-500">*</span>
                </label>
                <input
                  v-model="newNovel.title"
                  type="text"
                  class="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-primary-500"
                  :placeholder="t('novels.titlePlaceholder')"
                />
              </div>

              <div>
                <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  {{ t('novels.author') }}
                </label>
                <input
                  v-model="newNovel.author"
                  type="text"
                  class="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-primary-500"
                  :placeholder="t('novels.authorPlaceholder')"
                />
              </div>

              <div>
                <div class="flex items-center justify-between mb-1">
                  <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">
                    {{ t('novels.content') }}
                  </label>
                  <button type="button" class="text-sm text-primary-600 hover:text-primary-700" @click="openFilePicker">
                    {{ t('novels.uploadFile') }}
                  </button>
                </div>
                <textarea
                  v-model="newNovel.content"
                  rows="6"
                  class="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-primary-500 resize-none"
                  :placeholder="t('novels.contentPlaceholder')"
                />
                <p v-if="newNovel.content.length > 1000" class="text-xs text-gray-500 mt-1">
                  {{ t('novels.totalChars', { count: newNovel.content.length }) }}
                </p>
              </div>
            </div>

            <div class="flex justify-end gap-3 mt-6">
              <button type="button" class="btn-secondary" @click="closeCreateModal">
                {{ t('common.cancel') }}
              </button>
              <button
                type="button"
                class="btn-primary"
                :disabled="!newNovel.title.trim() || isCreating"
                @click="handleCreate"
              >
                <span v-if="isCreating" class="flex items-center gap-2">
                  <div class="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  {{ t('common.creating') }}
                </span>
                <span v-else>{{ t('common.create') }}</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Edit Modal -->
    <Teleport to="body">
      <div v-if="showEditModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50" @click.self="closeEditModal">
        <div class="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-md">
          <div class="p-6">
            <h2 class="text-xl font-semibold text-gray-900 dark:text-white mb-4">{{ t('novels.editNovel') }}</h2>

            <div class="space-y-4">
              <div>
                <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  {{ t('novels.novelTitle') }} <span class="text-red-500">*</span>
                </label>
                <input
                  v-model="editForm.title"
                  type="text"
                  class="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-primary-500"
                />
              </div>

              <div>
                <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  {{ t('novels.author') }}
                </label>
                <input
                  v-model="editForm.author"
                  type="text"
                  class="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-primary-500"
                />
              </div>
            </div>

            <div class="flex justify-end gap-3 mt-6">
              <button type="button" class="btn-secondary" @click="closeEditModal">
                {{ t('common.cancel') }}
              </button>
              <button
                type="button"
                class="btn-primary"
                :disabled="!editForm.title.trim() || isUpdating"
                @click="handleUpdate"
              >
                <span v-if="isUpdating" class="flex items-center gap-2">
                  <div class="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  {{ t('common.saving') }}
                </span>
                <span v-else>{{ t('common.save') }}</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Upload Preview Modal -->
    <Teleport to="body">
      <div v-if="showUploadModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50" @click.self="cancelUpload">
        <div class="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-2xl max-h-[80vh] overflow-hidden flex flex-col">
          <div class="p-4 border-b border-gray-200 dark:border-gray-700">
            <h2 class="text-lg font-semibold text-gray-900 dark:text-white">{{ t('novels.uploadPreview') }}</h2>
            <p class="text-sm text-gray-500 dark:text-gray-400">{{ fileName }}</p>
          </div>
          <div class="flex-1 overflow-y-auto p-4">
            <pre class="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap font-mono">{{ filePreview }}</pre>
          </div>
          <div class="p-4 border-t border-gray-200 dark:border-gray-700 flex justify-end gap-3">
            <button type="button" class="btn-secondary" @click="cancelUpload">
              {{ t('common.cancel') }}
            </button>
            <button type="button" class="btn-primary" @click="confirmUpload">
              {{ t('novels.confirmUpload') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
