<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const route = useRoute()

const novelId = computed(() => route.params.novelId as string)
const isLoading = ref(true)

onMounted(() => {
  // TODO: Fetch assets for novelId
  console.log('Loading assets for novel:', novelId.value)
  isLoading.value = false
})
</script>

<template>
  <div class="assets-view">
    <header class="mb-6">
      <h1 class="text-2xl font-bold text-gray-900 dark:text-white">{{ t('editor.assets') }}</h1>
      <p class="text-gray-500 dark:text-gray-400 mt-1">{{ t('editor.assetsDescription') }}</p>
    </header>

    <div v-if="isLoading" class="flex items-center justify-center py-12">
      <div class="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-primary-500" />
    </div>

    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      <!-- Placeholder for assets -->
      <div class="card p-6 text-center">
        <svg class="w-16 h-16 mx-auto mb-4 text-gray-400 dark:text-gray-500 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
        </svg>
        <p class="text-gray-500 dark:text-gray-400">{{ t('editor.noAssets') }}</p>
      </div>
    </div>
  </div>
</template>
