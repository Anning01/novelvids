<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const route = useRoute()

const chapterId = computed(() => route.params.chapterId as string)
const isLoading = ref(true)
const isPlaying = ref(false)

onMounted(() => {
  // TODO: Load studio data for chapterId
  console.log('Loading studio for chapter:', chapterId.value)
  isLoading.value = false
})

function togglePlay(): void {
  isPlaying.value = !isPlaying.value
}
</script>

<template>
  <div class="studio-view flex flex-col h-full">
    <div v-if="isLoading" class="flex items-center justify-center py-12">
      <div class="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-primary-500" />
    </div>

    <template v-else>
      <!-- Preview & Inspector -->
      <div class="flex-1 flex gap-4 mb-4">
        <!-- Video Preview -->
        <div class="flex-1 card overflow-hidden">
          <div class="aspect-video bg-gray-900 dark:bg-black flex items-center justify-center">
            <button
              type="button"
              class="p-4 rounded-full bg-white/10 hover:bg-white/20 transition-colors"
              @click="togglePlay"
            >
              <svg
                v-if="!isPlaying"
                class="w-12 h-12 text-white"
                fill="currentColor"
                viewBox="0 0 24 24"
              >
                <path d="M8 5v14l11-7z" />
              </svg>
              <svg
                v-else
                class="w-12 h-12 text-white"
                fill="currentColor"
                viewBox="0 0 24 24"
              >
                <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z" />
              </svg>
            </button>
          </div>
          <!-- Playback Controls -->
          <div class="p-4 flex items-center gap-4 bg-gray-100 dark:bg-gray-800">
            <span class="text-sm text-gray-500 dark:text-gray-400">00:00</span>
            <div class="flex-1 h-1 bg-gray-300 dark:bg-gray-700 rounded-full">
              <div class="h-full w-0 bg-primary-500 rounded-full" />
            </div>
            <span class="text-sm text-gray-500 dark:text-gray-400">00:00</span>
          </div>
        </div>

        <!-- Inspector Panel -->
        <div class="w-80 card p-4">
          <h3 class="font-semibold text-gray-900 dark:text-white mb-4">{{ t('studio.inspector') }}</h3>
          <div class="space-y-4">
            <div>
              <label class="block text-sm text-gray-500 dark:text-gray-400 mb-1">{{ t('studio.prompt') }}</label>
              <textarea
                rows="4"
                class="input w-full resize-none"
                :placeholder="t('studio.promptPlaceholder')"
              />
            </div>
            <div>
              <label class="block text-sm text-gray-500 dark:text-gray-400 mb-1">{{ t('studio.duration') }}</label>
              <input
                type="range"
                min="1"
                max="10"
                value="3"
                class="w-full"
              />
            </div>
            <button type="button" class="btn-primary w-full">
              {{ t('studio.regenerate') }}
            </button>
          </div>
        </div>
      </div>

      <!-- Timeline -->
      <div class="h-40 card p-4">
        <h3 class="text-sm font-semibold text-gray-500 dark:text-gray-400 mb-2">{{ t('studio.timeline') }}</h3>
        <div class="h-20 bg-gray-100 dark:bg-gray-700/50 rounded-lg flex items-center gap-1 p-2 overflow-x-auto">
          <!-- Placeholder clips -->
          <div
            v-for="i in 6"
            :key="i"
            class="h-full w-24 flex-shrink-0 bg-gray-300 dark:bg-gray-600 rounded cursor-pointer hover:bg-gray-400 dark:hover:bg-gray-500 transition-colors"
          />
        </div>
      </div>
    </template>
  </div>
</template>
