<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getAssets, deleteAsset, type PaginatedResponse } from '@/api/assets'
import type { Asset, AssetType } from '@/types/asset'

const { t } = useI18n()
const route = useRoute()

const novelId = computed(() => route.params.novelId as string)
const isLoading = ref(true)
const assets = ref<Asset[]>([])
const totalAssets = ref(0)
const currentPage = ref(1)
const pageSize = 20
const selectedType = ref<AssetType | 'all'>('all')
const error = ref<string | null>(null)

const assetTypes: Array<{ value: AssetType | 'all'; label: string }> = [
  { value: 'all', label: 'assets.filter.all' },
  { value: 'person', label: 'assets.types.person' },
  { value: 'scene', label: 'assets.types.scene' },
  { value: 'item', label: 'assets.types.item' },
]

async function loadAssets() {
  isLoading.value = true
  error.value = null
  try {
    const params: { asset_type?: string; page: number; page_size: number } = {
      page: currentPage.value,
      page_size: pageSize,
    }
    if (selectedType.value !== 'all') {
      params.asset_type = selectedType.value
    }
    const response: PaginatedResponse<Asset> = await getAssets(novelId.value, params)
    assets.value = response.items
    totalAssets.value = response.total
  } catch (e) {
    error.value = (e as Error).message || 'Failed to load assets'
    assets.value = []
  } finally {
    isLoading.value = false
  }
}

async function handleDelete(asset: Asset) {
  if (!confirm(`${t('common.confirmDelete')} "${asset.canonical_name}"?`)) {
    return
  }
  try {
    await deleteAsset(novelId.value, asset.id)
    await loadAssets()
  } catch (e) {
    error.value = (e as Error).message || 'Failed to delete asset'
  }
}

function getAssetTypeIcon(type: AssetType): string {
  switch (type) {
    case 'person':
      return 'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z'
    case 'scene':
      return 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6'
    case 'item':
      return 'M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4'
    default:
      return 'M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z'
  }
}

function getAssetTypeColor(type: AssetType): string {
  switch (type) {
    case 'person':
      return 'bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400'
    case 'scene':
      return 'bg-green-100 text-green-600 dark:bg-green-900/30 dark:text-green-400'
    case 'item':
      return 'bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400'
    default:
      return 'bg-gray-100 text-gray-600 dark:bg-gray-900/30 dark:text-gray-400'
  }
}

watch([selectedType, currentPage], () => {
  loadAssets()
})

onMounted(() => {
  loadAssets()
})
</script>

<template>
  <div class="assets-view">
    <header class="mb-6">
      <h1 class="text-2xl font-bold text-gray-900 dark:text-white">{{ t('assets.title') }}</h1>
      <p class="text-gray-500 dark:text-gray-400 mt-1">{{ t('editor.assetsDescription') }}</p>
    </header>

    <!-- Type Filter Tabs -->
    <div class="mb-6 flex gap-2 flex-wrap">
      <button
        v-for="type in assetTypes"
        :key="type.value"
        :class="[
          'px-4 py-2 rounded-lg text-sm font-medium transition-colors',
          selectedType === type.value
            ? 'bg-primary-500 text-white'
            : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600',
        ]"
        @click="selectedType = type.value; currentPage = 1"
      >
        {{ t(type.label) }}
      </button>
    </div>

    <!-- Error State -->
    <div v-if="error" class="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg text-red-600 dark:bg-red-900/20 dark:border-red-800 dark:text-red-400">
      {{ error }}
    </div>

    <!-- Loading State -->
    <div v-if="isLoading" class="flex items-center justify-center py-12">
      <div class="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-primary-500" />
    </div>

    <!-- Empty State -->
    <div v-else-if="assets.length === 0" class="card p-12 text-center">
      <svg class="w-16 h-16 mx-auto mb-4 text-gray-400 dark:text-gray-500 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
      </svg>
      <p class="text-gray-500 dark:text-gray-400">{{ t('assets.empty') }}</p>
      <p class="text-sm text-gray-400 dark:text-gray-500 mt-2">{{ t('editor.noAssets') }}</p>
    </div>

    <!-- Assets Grid -->
    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      <div
        v-for="asset in assets"
        :key="asset.id"
        class="card overflow-hidden hover:shadow-lg transition-shadow"
      >
        <!-- Asset Image -->
        <div class="aspect-square bg-gray-100 dark:bg-gray-700 relative">
          <img
            v-if="asset.main_image"
            :src="asset.main_image"
            :alt="asset.canonical_name"
            class="w-full h-full object-cover"
          />
          <div v-else class="w-full h-full flex items-center justify-center">
            <svg class="w-16 h-16 text-gray-300 dark:text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" :d="getAssetTypeIcon(asset.asset_type)" />
            </svg>
          </div>
          <!-- Type Badge -->
          <span :class="['absolute top-2 left-2 px-2 py-1 text-xs font-medium rounded', getAssetTypeColor(asset.asset_type)]">
            {{ t(`assets.types.${asset.asset_type}`) }}
          </span>
          <!-- Global Badge -->
          <span
            v-if="asset.is_global"
            class="absolute top-2 right-2 px-2 py-1 text-xs font-medium rounded bg-purple-100 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400"
          >
            {{ t('assets.filter.global') }}
          </span>
        </div>

        <!-- Asset Info -->
        <div class="p-4">
          <h3 class="font-semibold text-gray-900 dark:text-white truncate">
            {{ asset.canonical_name }}
          </h3>
          <p v-if="asset.aliases.length > 0" class="text-xs text-gray-500 dark:text-gray-400 mt-1 truncate">
            {{ asset.aliases.join(', ') }}
          </p>
          <p v-if="asset.description" class="text-sm text-gray-600 dark:text-gray-300 mt-2 line-clamp-2">
            {{ asset.description }}
          </p>

          <!-- Actions -->
          <div class="mt-3 flex justify-end gap-2">
            <button
              class="p-1.5 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded transition-colors"
              :title="t('common.delete')"
              @click="handleDelete(asset)"
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
    <div v-if="totalAssets > pageSize" class="mt-6 flex justify-center gap-2">
      <button
        :disabled="currentPage === 1"
        :class="[
          'px-3 py-1 rounded text-sm',
          currentPage === 1
            ? 'bg-gray-100 text-gray-400 cursor-not-allowed dark:bg-gray-700 dark:text-gray-500'
            : 'bg-gray-200 text-gray-700 hover:bg-gray-300 dark:bg-gray-600 dark:text-gray-200 dark:hover:bg-gray-500',
        ]"
        @click="currentPage--"
      >
        {{ t('common.prev') }}
      </button>
      <span class="px-3 py-1 text-sm text-gray-600 dark:text-gray-300">
        {{ currentPage }} / {{ Math.ceil(totalAssets / pageSize) }}
      </span>
      <button
        :disabled="currentPage >= Math.ceil(totalAssets / pageSize)"
        :class="[
          'px-3 py-1 rounded text-sm',
          currentPage >= Math.ceil(totalAssets / pageSize)
            ? 'bg-gray-100 text-gray-400 cursor-not-allowed dark:bg-gray-700 dark:text-gray-500'
            : 'bg-gray-200 text-gray-700 hover:bg-gray-300 dark:bg-gray-600 dark:text-gray-200 dark:hover:bg-gray-500',
        ]"
        @click="currentPage++"
      >
        {{ t('common.next') }}
      </button>
    </div>

    <!-- Total Count -->
    <div class="mt-4 text-center text-sm text-gray-500 dark:text-gray-400">
      {{ t('common.total') }}: {{ totalAssets }}
    </div>
  </div>
</template>
