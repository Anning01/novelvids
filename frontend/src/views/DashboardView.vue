<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore, useNovelStore } from '@/stores'
import { fetchDashboardStats } from '@/api/dashboard'
import type { DashboardStats } from '@/types'

const { t } = useI18n()
const router = useRouter()
const authStore = useAuthStore()
const novelStore = useNovelStore()

const isLoading = ref(true)
const dashboardData = ref<DashboardStats>({
  total_novels: 0,
  total_videos: 0,
  processing_time: 0,
  balance: 0,
  recent_novels: [],
})

// Create novel modal
const showCreateModal = ref(false)
const newNovel = ref({
  title: '',
  content: '',
  author: '',
})
const isCreating = ref(false)

// Upload file
const showUploadModal = ref(false)
const filePreviewSample = ref('')
const fileName = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
const isUploading = ref(false)
let fullFileContent = ''

const stats = computed(() => [
  { label: t('dashboard.stats.totalNovels'), value: dashboardData.value.total_novels.toString(), change: '' },
  { label: t('dashboard.stats.totalVideos'), value: dashboardData.value.total_videos.toString(), change: '' },
  { label: t('dashboard.stats.processingTasks'), value: `${dashboardData.value.processing_time}h`, change: '' },
  { label: t('dashboard.stats.accountBalance'), value: `$${dashboardData.value.balance.toFixed(2)}`, change: '' },
])

const contentLengthHint = computed(() => {
  const len = newNovel.value.content.length
  if (len > 10000) {
    return `已加载 ${(len / 1000).toFixed(1)}K 字符`
  }
  return ''
})

onMounted(async () => {
  try {
    isLoading.value = true
    dashboardData.value = await fetchDashboardStats()
  } catch (error) {
    console.error('Failed to fetch dashboard stats:', error)
  } finally {
    isLoading.value = false
  }
})

function handleFileChange(e: Event): void {
  const target = e.target as HTMLInputElement
  const f = target.files && target.files[0]
  if (!f) return

  isUploading.value = true
  fileName.value = f.name

  const reader = new FileReader()
  reader.onload = () => {
    fullFileContent = String(reader.result || '')
    const previewLength = 2000
    if (fullFileContent.length > previewLength) {
      filePreviewSample.value = fullFileContent.slice(0, previewLength) + '\n\n... (共 ' + fullFileContent.length + ' 字符)'
    } else {
      filePreviewSample.value = fullFileContent
    }
    isUploading.value = false
    showUploadModal.value = true
  }
  reader.onerror = () => {
    isUploading.value = false
    console.error('File read error')
  }
  reader.readAsText(f)
  target.value = ''
}

function confirmInsert(): void {
  newNovel.value.content = fullFileContent
  showUploadModal.value = false
  filePreviewSample.value = ''
  fullFileContent = ''
}

function cancelUpload(): void {
  filePreviewSample.value = ''
  fullFileContent = ''
  fileName.value = ''
  showUploadModal.value = false
}

function openFilePicker(): void {
  fileInput.value?.click()
}

async function handleCreate(): Promise<void> {
  if (!newNovel.value.title) return

  isCreating.value = true
  try {
    const novel = await novelStore.addNovel({
      title: newNovel.value.title,
      content: newNovel.value.content || undefined,
      author: newNovel.value.author || undefined,
    })

    showCreateModal.value = false
    newNovel.value = { title: '', content: '', author: '' }

    // Navigate to the new novel's editor
    router.push(`/editor/${novel.id}`)
  } catch (error) {
    console.error('Failed to create novel:', error)
  } finally {
    isCreating.value = false
  }
}

function closeCreateModal(): void {
  showCreateModal.value = false
  newNovel.value = { title: '', content: '', author: '' }
}
</script>

<template>
  <div class="space-y-6 animate-fade-in">
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-bold text-gray-900 dark:text-white">{{ t('dashboard.title') }}</h1>
        <p class="text-gray-500 dark:text-gray-400 mt-1">{{ t('dashboard.welcome', { username: authStore.user?.username || '' }) }}</p>
      </div>
      <button type="button" class="btn-primary" @click="showCreateModal = true">
        <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
        </svg>
        {{ t('novels.uploadNovel') }}
      </button>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
      <div
        v-for="stat in stats"
        :key="stat.label"
        class="card p-6"
      >
        <p class="text-sm font-medium text-gray-500 dark:text-gray-400">{{ stat.label }}</p>
        <div class="flex items-baseline gap-2 mt-2">
          <span class="text-3xl font-bold text-gray-900 dark:text-white">{{ stat.value }}</span>
          <span v-if="stat.change" class="text-sm text-green-500">{{ stat.change }}</span>
        </div>
      </div>
    </div>

    <div class="grid lg:grid-cols-2 gap-6">
      <div class="card p-6">
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-lg font-semibold text-gray-900 dark:text-white">{{ t('dashboard.recentNovels') }}</h2>
          <button
            type="button"
            class="text-sm text-primary-600 dark:text-primary-400 hover:underline"
            @click="showCreateModal = true"
          >
            + {{ t('novels.uploadNovel') }}
          </button>
        </div>

        <div v-if="isLoading" class="flex justify-center py-12">
          <div class="animate-spin w-8 h-8 border-4 border-primary-500 border-t-transparent rounded-full" />
        </div>

        <div v-else-if="dashboardData.recent_novels.length > 0" class="space-y-4">
          <router-link
            v-for="novel in dashboardData.recent_novels"
            :key="novel.id"
            :to="`/editor/${novel.id}`"
            class="block p-4 rounded-lg bg-gray-50 dark:bg-gray-700/50 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
          >
            <div class="flex justify-between items-start">
              <div>
                <h3 class="font-medium text-gray-900 dark:text-white">{{ novel.title }}</h3>
                <p class="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  {{ novel.totalChapters }} {{ t('novels.chapters') }} • {{ novel.processedChapters }} {{ t('novels.processedChapters') }}
                </p>
              </div>
              <span
                class="px-2 py-1 text-xs font-medium rounded-full"
                :class="{
                  'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400': novel.status === 'pending',
                  'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400': novel.status === 'completed',
                  'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400': novel.status === 'failed',
                  'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400': (novel.status as string) === 'processing'
                }"
              >
                {{ t(`novels.novelStatus.${novel.status}`) }}
              </span>
            </div>
          </router-link>
        </div>

        <div v-else class="text-center py-12 text-gray-500 dark:text-gray-400">
          <svg class="w-12 h-12 mx-auto mb-4 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
          </svg>
          <p class="mb-4">{{ t('novels.noNovels') }}</p>
          <button type="button" class="btn-primary" @click="showCreateModal = true">
            {{ t('novels.uploadNovel') }}
          </button>
        </div>
      </div>

      <div class="card p-6">
        <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">{{ t('dashboard.quickActions') }}</h2>
        <div class="space-y-3">
          <button
            type="button"
            class="w-full flex items-center gap-4 p-4 rounded-lg bg-gray-50 dark:bg-gray-700/50 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors text-left"
            @click="showCreateModal = true"
          >
            <div class="w-10 h-10 bg-primary-100 dark:bg-primary-900/30 rounded-lg flex items-center justify-center">
              <svg class="w-5 h-5 text-primary-600 dark:text-primary-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
              </svg>
            </div>
            <div>
              <p class="font-medium text-gray-900 dark:text-white">{{ t('dashboard.uploadNovel') }}</p>
              <p class="text-sm text-gray-500 dark:text-gray-400">{{ t('novels.uploadFirst') }}</p>
            </div>
          </button>

          <router-link
            to="/settings"
            class="flex items-center gap-4 p-4 rounded-lg bg-gray-50 dark:bg-gray-700/50 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
          >
            <div class="w-10 h-10 bg-accent-100 dark:bg-accent-900/30 rounded-lg flex items-center justify-center">
              <svg class="w-5 h-5 text-accent-600 dark:text-accent-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            </div>
            <div>
              <p class="font-medium text-gray-900 dark:text-white">{{ t('nav.settings') }}</p>
              <p class="text-sm text-gray-500 dark:text-gray-400">{{ t('settings.comfyuiConfig') }}</p>
            </div>
          </router-link>
        </div>
      </div>
    </div>

    <!-- Hidden file input -->
    <input
      ref="fileInput"
      type="file"
      accept=".txt"
      class="hidden"
      @change="handleFileChange"
    />

    <!-- Create Novel Modal -->
    <Teleport to="body">
      <div
        v-if="showCreateModal"
        class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50"
        @click.self="closeCreateModal"
      >
        <div class="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-2xl max-h-[90vh] overflow-hidden">
          <div class="p-6 border-b border-gray-200 dark:border-gray-700">
            <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{{ t('novels.uploadNovel') }}</h3>
          </div>

          <div class="p-6 space-y-4 overflow-y-auto max-h-[60vh]">
            <div>
              <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                {{ t('novels.novelTitle') }} *
              </label>
              <input
                v-model="newNovel.title"
                type="text"
                class="input w-full"
                :placeholder="t('novels.novelTitle')"
              />
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                {{ t('novels.author') }} ({{ t('common.optional') }})
              </label>
              <input
                v-model="newNovel.author"
                type="text"
                class="input w-full"
                :placeholder="t('novels.author')"
              />
            </div>

            <div>
              <div class="flex items-center justify-between mb-1">
                <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">
                  {{ t('novels.content') }} ({{ t('common.optional') }})
                </label>
                <div class="flex items-center gap-2">
                  <span v-if="contentLengthHint" class="text-xs text-gray-500">{{ contentLengthHint }}</span>
                  <button
                    type="button"
                    class="text-sm text-primary-600 dark:text-primary-400 hover:underline"
                    @click="openFilePicker"
                  >
                    {{ t('novels.uploadTxt') }}
                  </button>
                </div>
              </div>
              <textarea
                v-model="newNovel.content"
                rows="10"
                class="input w-full resize-none"
                :placeholder="t('novels.content')"
              />
            </div>
          </div>

          <div class="p-6 border-t border-gray-200 dark:border-gray-700 flex justify-end gap-3">
            <button
              type="button"
              class="btn-secondary"
              :disabled="isCreating"
              @click="closeCreateModal"
            >
              {{ t('common.cancel') }}
            </button>
            <button
              type="button"
              class="btn-primary"
              :disabled="!newNovel.title || isCreating"
              @click="handleCreate"
            >
              <span v-if="isCreating">{{ t('common.creating') }}</span>
              <span v-else>{{ t('common.create') }}</span>
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- File Upload Preview Modal -->
    <Teleport to="body">
      <div
        v-if="showUploadModal"
        class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50"
        @click.self="cancelUpload"
      >
        <div class="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-2xl max-h-[90vh] overflow-hidden">
          <div class="p-6 border-b border-gray-200 dark:border-gray-700">
            <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{{ fileName }}</h3>
          </div>

          <div class="p-6 overflow-y-auto max-h-[60vh]">
            <pre class="text-sm text-gray-600 dark:text-gray-300 whitespace-pre-wrap font-mono bg-gray-50 dark:bg-gray-900 p-4 rounded-lg">{{ filePreviewSample }}</pre>
          </div>

          <div class="p-6 border-t border-gray-200 dark:border-gray-700 flex justify-end gap-3">
            <button type="button" class="btn-secondary" @click="cancelUpload">
              {{ t('common.cancel') }}
            </button>
            <button type="button" class="btn-primary" @click="confirmInsert">
              {{ t('novels.insertIntoContent') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
