<script setup lang="ts">
import { computed, onMounted, provide, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useNovelStore } from '@/stores/novels'
import { useChapterStore } from '@/stores/chapters'
import { useToastStore } from '@/stores/toast'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const novelStore = useNovelStore()
const chapterStore = useChapterStore()
const toastStore = useToastStore()

const novelId = computed(() => route.params.novelId as string)
const currentChapterId = computed(() => route.params.chapterId as string | undefined)

const isLoading = ref(true)
const isSidebarCollapsed = ref(false)
const isExtracting = ref(false)

// Chapter modal state
const showChapterModal = ref(false)
const editingChapter = ref<{ id: string; title: string; content: string } | null>(null)
const chapterForm = ref({ title: '', content: '' })
const isSavingChapter = ref(false)

// Delete confirm state
const showDeleteConfirm = ref(false)
const deletingChapterId = ref<string | null>(null)
const isDeletingChapter = ref(false)

const canExtractChapters = computed(() => novelStore.currentNovel?.canExtractChapters ?? false)
const hasNoChapters = computed(() => chapterStore.chapters.length === 0)

onMounted(async () => {
  if (novelId.value) {
    await Promise.all([
      novelStore.fetchNovel(novelId.value),
      chapterStore.fetchChapters(novelId.value),
    ])
  }
  isLoading.value = false
})

watch(novelId, async (newId) => {
  if (newId) {
    isLoading.value = true
    await Promise.all([
      novelStore.fetchNovel(newId),
      chapterStore.fetchChapters(newId),
    ])
    isLoading.value = false
  }
})

function goToDashboard(): void {
  router.push('/dashboard')
}

function goToAssets(): void {
  router.push(`/editor/${novelId.value}/assets`)
}

function selectChapter(chapterId: string): void {
  router.push(`/editor/${novelId.value}/chapter/${chapterId}/extraction`)
}

function toggleSidebar(): void {
  isSidebarCollapsed.value = !isSidebarCollapsed.value
}

// Extract chapters
async function handleExtractChapters(): Promise<void> {
  if (isExtracting.value) return

  isExtracting.value = true
  try {
    await novelStore.processNovel(novelId.value)
    await chapterStore.fetchChapters(novelId.value)
    toastStore.success(t('editor.extractSuccess'))
  } catch (error) {
    console.error('Failed to extract chapters:', error)
    toastStore.error(t('editor.extractFailed'))
  } finally {
    isExtracting.value = false
  }
}

// Open create chapter modal
function openCreateChapter(): void {
  editingChapter.value = null
  chapterForm.value = { title: '', content: '' }
  showChapterModal.value = true
}

// Open edit chapter modal
async function openEditChapter(chapterId: string): Promise<void> {
  await chapterStore.fetchChapter(chapterId)
  const chapter = chapterStore.currentChapter
  if (chapter) {
    editingChapter.value = { id: chapter.id, title: chapter.title, content: chapter.content }
    chapterForm.value = { title: chapter.title, content: chapter.content }
    showChapterModal.value = true
  }
}

// Save chapter (create or update)
async function handleSaveChapter(): Promise<void> {
  if (!chapterForm.value.title.trim()) return

  isSavingChapter.value = true
  try {
    if (editingChapter.value) {
      // Update existing chapter
      await chapterStore.editChapter(editingChapter.value.id, {
        title: chapterForm.value.title,
        content: chapterForm.value.content,
      })
      toastStore.success(t('messages.updateSuccess'))
    } else {
      // Create new chapter
      const chapter = await chapterStore.addChapter(novelId.value, {
        title: chapterForm.value.title,
        content: chapterForm.value.content,
      })
      toastStore.success(t('chapters.createSuccess'))
      // Navigate to new chapter
      selectChapter(chapter.id)
    }
    showChapterModal.value = false
  } catch (error) {
    console.error('Failed to save chapter:', error)
    toastStore.error(t('errors.general'))
  } finally {
    isSavingChapter.value = false
  }
}

// Close chapter modal
function closeChapterModal(): void {
  showChapterModal.value = false
  editingChapter.value = null
  chapterForm.value = { title: '', content: '' }
}

// Confirm delete chapter
function confirmDeleteChapter(chapterId: string): void {
  deletingChapterId.value = chapterId
  showDeleteConfirm.value = true
}

// Delete chapter
async function handleDeleteChapter(): Promise<void> {
  if (!deletingChapterId.value) return

  isDeletingChapter.value = true
  try {
    await chapterStore.removeChapter(deletingChapterId.value)
    toastStore.success(t('chapters.deleteSuccess'))
    showDeleteConfirm.value = false
    // If deleted current chapter, navigate to assets
    if (currentChapterId.value === deletingChapterId.value) {
      goToAssets()
    }
  } catch (error) {
    console.error('Failed to delete chapter:', error)
    toastStore.error(t('errors.deleteFailed'))
  } finally {
    isDeletingChapter.value = false
    deletingChapterId.value = null
  }
}

// Provide context to child components
provide('novelId', novelId)
provide('currentChapterId', currentChapterId)
</script>

<template>
  <div class="editor-layout min-h-screen bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-white flex flex-col">
    <!-- Top Header Bar -->
    <header class="h-14 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between px-4 flex-shrink-0">
      <div class="flex items-center gap-4">
        <!-- Back to Dashboard -->
        <button
          type="button"
          class="flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white"
          @click="goToDashboard"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
          <span class="text-sm">{{ t('nav.dashboard') }}</span>
        </button>
        <!-- Divider -->
        <div class="w-px h-6 bg-gray-300 dark:bg-gray-600" />
        <!-- Novel Title -->
        <h1 class="text-lg font-semibold text-gray-900 dark:text-white">
          {{ novelStore.currentNovel?.title || t('editor.loading') }}
        </h1>
      </div>
      <div class="flex items-center gap-2">
        <!-- Settings -->
        <router-link
          to="/settings"
          class="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white"
          :title="t('nav.settings')"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        </router-link>
      </div>
    </header>

    <!-- Main Content Area with Sidebar -->
    <div class="flex flex-1 overflow-hidden">
      <!-- Sidebar -->
      <aside
        :class="[
          'bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 flex flex-col transition-all duration-300 flex-shrink-0',
          isSidebarCollapsed ? 'w-16' : 'w-64',
        ]"
      >
        <!-- Sidebar Header with collapse button -->
        <div class="p-3 border-b border-gray-200 dark:border-gray-700 flex items-center justify-end">
          <button
            type="button"
            class="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors text-gray-600 dark:text-gray-400"
            @click="toggleSidebar"
          >
            <svg v-if="!isSidebarCollapsed" class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
            </svg>
            <svg v-else class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 5l7 7-7 7M5 5l7 7-7 7" />
            </svg>
          </button>
        </div>

        <!-- Navigation -->
        <nav class="flex-1 overflow-y-auto p-2">
          <!-- Assets Button -->
          <button
            type="button"
            :class="[
              'w-full flex items-center gap-3 p-3 rounded-lg mb-2 transition-colors',
              route.name === 'editor-assets'
                ? 'bg-primary-50 text-primary-600 dark:bg-primary-900/20 dark:text-primary-400'
                : 'text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-700',
            ]"
            @click="goToAssets"
          >
            <svg class="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
            <span v-if="!isSidebarCollapsed" class="font-medium">{{ t('editor.assets') }}</span>
          </button>

          <!-- Chapters Section -->
          <div v-if="!isSidebarCollapsed" class="mt-4">
            <div class="flex items-center justify-between px-3 mb-2">
              <h3 class="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                {{ t('editor.chapters') }}
              </h3>
              <div class="flex items-center gap-1">
                <!-- Extract Chapters Button -->
                <button
                  v-if="canExtractChapters"
                  type="button"
                  class="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-500 dark:text-gray-400"
                  :title="t('editor.extractChapters')"
                  :disabled="isExtracting"
                  @click="handleExtractChapters"
                >
                  <svg v-if="!isExtracting" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                  <svg v-else class="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                </button>
                <!-- Add Chapter Button -->
                <button
                  type="button"
                  class="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-500 dark:text-gray-400"
                  :title="t('chapters.addChapter')"
                  @click="openCreateChapter"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
                  </svg>
                </button>
              </div>
            </div>
          </div>

          <!-- No Chapters Hint -->
          <div v-if="hasNoChapters && !isSidebarCollapsed" class="px-3 py-4 text-center">
            <p class="text-sm text-gray-500 dark:text-gray-400 mb-3">{{ t('editor.noChaptersHint') }}</p>
            <button
              v-if="canExtractChapters"
              type="button"
              class="btn-primary text-sm px-3 py-1.5"
              :disabled="isExtracting"
              @click="handleExtractChapters"
            >
              <span v-if="isExtracting">{{ t('common.loading') }}</span>
              <span v-else>{{ t('editor.extractChapters') }}</span>
            </button>
          </div>

          <!-- Chapter List -->
          <div class="space-y-1">
            <div
              v-for="chapter in chapterStore.chapters"
              :key="chapter.id"
              class="group relative"
            >
              <button
                type="button"
                :class="[
                  'w-full flex items-center gap-3 p-3 rounded-lg transition-colors text-left',
                  currentChapterId === chapter.id
                    ? 'bg-primary-50 text-primary-600 dark:bg-primary-900/20 dark:text-primary-400'
                    : 'text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-700',
                ]"
                @click="selectChapter(chapter.id)"
              >
                <span
                  :class="[
                    'w-6 h-6 flex-shrink-0 flex items-center justify-center rounded-full text-xs',
                    currentChapterId === chapter.id
                      ? 'bg-primary-100 text-primary-600 dark:bg-primary-800 dark:text-primary-300'
                      : 'bg-gray-200 text-gray-600 dark:bg-gray-600 dark:text-gray-300',
                  ]"
                >
                  {{ chapter.number }}
                </span>
                <span v-if="!isSidebarCollapsed" class="truncate flex-1 font-medium">
                  {{ chapter.title }}
                </span>
                <!-- Status indicator -->
                <span
                  v-if="!isSidebarCollapsed"
                  :class="[
                    'w-2 h-2 rounded-full flex-shrink-0',
                    chapter.workflowStatus === 'completed' ? 'bg-green-500' :
                    chapter.workflowStatus === 'generating' ? 'bg-yellow-500' :
                    'bg-gray-400 dark:bg-gray-500',
                  ]"
                />
              </button>
              <!-- Chapter Actions (visible on hover) -->
              <div
                v-if="!isSidebarCollapsed"
                class="absolute right-2 top-1/2 -translate-y-1/2 hidden group-hover:flex items-center gap-1 bg-white dark:bg-gray-800 rounded shadow-sm"
              >
                <button
                  type="button"
                  class="p-1.5 text-gray-500 hover:text-primary-600 dark:text-gray-400 dark:hover:text-primary-400"
                  :title="t('common.edit')"
                  @click.stop="openEditChapter(chapter.id)"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                  </svg>
                </button>
                <button
                  type="button"
                  class="p-1.5 text-gray-500 hover:text-red-600 dark:text-gray-400 dark:hover:text-red-400"
                  :title="t('common.delete')"
                  @click.stop="confirmDeleteChapter(chapter.id)"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </nav>
      </aside>

      <!-- Main Content -->
      <main class="flex-1 overflow-auto p-6 bg-gray-50 dark:bg-gray-900">
        <div v-if="isLoading" class="flex items-center justify-center h-full">
          <div class="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-primary-500" />
        </div>
        <router-view v-else />
      </main>
    </div>

    <!-- Chapter Edit/Create Modal -->
    <Teleport to="body">
      <div
        v-if="showChapterModal"
        class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50"
        @click.self="closeChapterModal"
      >
        <div class="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-2xl max-h-[90vh] overflow-hidden">
          <div class="p-6 border-b border-gray-200 dark:border-gray-700">
            <h3 class="text-lg font-semibold text-gray-900 dark:text-white">
              {{ editingChapter ? t('chapters.editChapter') : t('chapters.addChapter') }}
            </h3>
          </div>

          <div class="p-6 space-y-4 overflow-y-auto max-h-[60vh]">
            <div>
              <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                {{ t('chapters.chapterTitle') }} *
              </label>
              <input
                v-model="chapterForm.title"
                type="text"
                class="input w-full"
                :placeholder="t('chapters.enterChapterTitle')"
              />
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                {{ t('chapters.chapterContent') }} ({{ t('common.optional') }})
              </label>
              <textarea
                v-model="chapterForm.content"
                rows="12"
                class="input w-full resize-none"
                :placeholder="t('chapters.enterChapterContent')"
              />
            </div>
          </div>

          <div class="p-6 border-t border-gray-200 dark:border-gray-700 flex justify-end gap-3">
            <button
              type="button"
              class="btn-secondary"
              :disabled="isSavingChapter"
              @click="closeChapterModal"
            >
              {{ t('common.cancel') }}
            </button>
            <button
              type="button"
              class="btn-primary"
              :disabled="!chapterForm.title.trim() || isSavingChapter"
              @click="handleSaveChapter"
            >
              <span v-if="isSavingChapter">{{ t('common.loading') }}</span>
              <span v-else>{{ t('common.save') }}</span>
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Delete Confirm Modal -->
    <Teleport to="body">
      <div
        v-if="showDeleteConfirm"
        class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50"
        @click.self="showDeleteConfirm = false"
      >
        <div class="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-md">
          <div class="p-6">
            <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-2">
              {{ t('chapters.deleteConfirm') }}
            </h3>
            <p class="text-gray-600 dark:text-gray-400">
              {{ t('chapters.deleteWarning') }}
            </p>
          </div>

          <div class="p-6 border-t border-gray-200 dark:border-gray-700 flex justify-end gap-3">
            <button
              type="button"
              class="btn-secondary"
              :disabled="isDeletingChapter"
              @click="showDeleteConfirm = false"
            >
              {{ t('common.cancel') }}
            </button>
            <button
              type="button"
              class="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg font-medium transition-colors"
              :disabled="isDeletingChapter"
              @click="handleDeleteChapter"
            >
              <span v-if="isDeletingChapter">{{ t('common.deleting') }}</span>
              <span v-else>{{ t('common.delete') }}</span>
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.editor-layout {
  height: 100vh;
}
</style>
