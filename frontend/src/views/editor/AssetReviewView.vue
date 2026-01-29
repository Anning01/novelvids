<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useToastStore } from '@/stores/toast'
import { getMediaUrl } from '@/api/client'
import {
  getAssets,
  getGlobalAssets,
  updateAsset,
  deleteAsset,
  uploadAssetImage,
  generateAssetImage,
  type Asset,
} from '@/api/assets'

const { t } = useI18n()
const route = useRoute()
const toastStore = useToastStore()

const novelId = computed(() => route.params.novelId as string)
const chapterId = computed(() => route.params.chapterId as string)

// State
const isLoading = ref(true)
const assets = ref<{ persons: Asset[]; scenes: Asset[]; items: Asset[] }>({
  persons: [],
  scenes: [],
  items: [],
})
const globalAssets = ref<Asset[]>([])
const selectedAsset = ref<Asset | null>(null)
const isEditModalOpen = ref(false)
const isUploading = ref(false)
const activeTab = ref<'person' | 'scene' | 'item'>('person')

// Computed
const currentAssets = computed(() => {
  switch (activeTab.value) {
    case 'person':
      return assets.value.persons
    case 'scene':
      return assets.value.scenes
    case 'item':
      return assets.value.items
    default:
      return []
  }
})

const globalAssetsForType = computed(() => {
  return globalAssets.value.filter(a => a.asset_type === activeTab.value)
})

const assetsWithMissingImages = computed(() => {
  return currentAssets.value.filter(a => !a.main_image)
})

const allAssetsHaveImages = computed(() => {
  const allAssets = [...assets.value.persons, ...assets.value.scenes, ...assets.value.items]
  return allAssets.length > 0 && allAssets.every(a => a.main_image)
})

// Load data
async function loadAssets(): Promise<void> {
  try {
    const [persons, scenes, items] = await Promise.all([
      getAssets(novelId.value, { asset_type: 'person', page_size: 100 }),
      getAssets(novelId.value, { asset_type: 'scene', page_size: 100 }),
      getAssets(novelId.value, { asset_type: 'item', page_size: 100 }),
    ])
    assets.value = {
      persons: persons.items,
      scenes: scenes.items,
      items: items.items,
    }
  } catch (error) {
    console.error('Failed to load assets:', error)
    toastStore.error(t('common.loadFailed'))
  }
}

async function loadGlobalAssets(): Promise<void> {
  try {
    globalAssets.value = await getGlobalAssets(novelId.value)
  } catch (error) {
    console.error('Failed to load global assets:', error)
  }
}

// Asset actions
function openEditModal(asset: Asset): void {
  selectedAsset.value = { ...asset }
  isEditModalOpen.value = true
}

function closeEditModal(): void {
  selectedAsset.value = null
  isEditModalOpen.value = false
}

async function saveAsset(): Promise<void> {
  if (!selectedAsset.value) return

  try {
    await updateAsset(novelId.value, selectedAsset.value.id, {
      canonical_name: selectedAsset.value.canonical_name,
      aliases: selectedAsset.value.aliases,
      description: selectedAsset.value.description || undefined,
      base_traits: selectedAsset.value.base_traits || undefined,
      main_image: selectedAsset.value.main_image || undefined,
      angle_image_1: selectedAsset.value.angle_image_1 || undefined,
      angle_image_2: selectedAsset.value.angle_image_2 || undefined,
      is_global: selectedAsset.value.is_global,
    })
    toastStore.success(t('common.saved'))
    closeEditModal()
    await loadAssets()
  } catch (error) {
    console.error('Failed to save asset:', error)
    toastStore.error(t('common.saveFailed'))
  }
}

async function handleDeleteAsset(asset: Asset): Promise<void> {
  if (!confirm(t('common.confirm'))) return

  try {
    await deleteAsset(novelId.value, asset.id)
    toastStore.success(t('messages.deleteSuccess'))
    await loadAssets()
  } catch (error) {
    console.error('Failed to delete asset:', error)
    toastStore.error(t('common.deleteFailed'))
  }
}

async function promoteToGlobal(asset: Asset): Promise<void> {
  try {
    await updateAsset(novelId.value, asset.id, { is_global: true })
    toastStore.success(t('assetReview.promotedToGlobal'))
    await loadAssets()
    await loadGlobalAssets()
  } catch (error) {
    console.error('Failed to promote asset:', error)
    toastStore.error(t('common.saveFailed'))
  }
}

// Image handling
async function handleImageUpload(
  event: Event,
  imageField: 'main_image' | 'angle_image_1' | 'angle_image_2'
): Promise<void> {
  const input = event.target as HTMLInputElement
  if (!input.files?.length || !selectedAsset.value) return

  const file = input.files[0]
  isUploading.value = true

  try {
    const updated = await uploadAssetImage(
      novelId.value,
      selectedAsset.value.id,
      file,
      imageField
    )
    // Update the selected asset with the new image URL
    selectedAsset.value[imageField] = updated[imageField]
    toastStore.success(t('messages.uploadSuccess'))
    await loadAssets()
  } catch (error) {
    console.error('Failed to upload image:', error)
    toastStore.error(t('errors.uploadFailed'))
  } finally {
    isUploading.value = false
    // Reset input
    input.value = ''
  }
}

const isGenerating = ref(false)

async function handleGenerateImage(
  asset: Asset,
  imageField: 'main_image' | 'angle_image_1' | 'angle_image_2'
): Promise<void> {
  if (!asset.base_traits) {
    toastStore.error(t('assetReview.missingBaseTraits'))
    return
  }

  isGenerating.value = true
  try {
    const updated = await generateAssetImage(novelId.value, asset.id, imageField)
    // Update selectedAsset if it's the same asset being edited
    if (selectedAsset.value?.id === asset.id) {
      selectedAsset.value[imageField] = updated[imageField]
    }
    toastStore.success(t('assetReview.imageGenerated'))
    await loadAssets()
  } catch (error) {
    console.error('Failed to generate image:', error)
    toastStore.error(t('assetReview.imageGenFailed'))
  } finally {
    isGenerating.value = false
  }
}

// Initialize
onMounted(async () => {
  isLoading.value = true
  try {
    await Promise.all([loadAssets(), loadGlobalAssets()])
  } finally {
    isLoading.value = false
  }
})

watch([novelId, chapterId], async () => {
  isLoading.value = true
  try {
    await Promise.all([loadAssets(), loadGlobalAssets()])
  } finally {
    isLoading.value = false
  }
})
</script>

<template>
  <div class="asset-review-view">
    <!-- Loading -->
    <div v-if="isLoading" class="flex items-center justify-center py-12">
      <div class="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-primary-500" />
    </div>

    <div v-else class="space-y-6">
      <!-- Status Banner -->
      <div
        :class="[
          'rounded-lg p-4',
          allAssetsHaveImages
            ? 'bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800'
            : 'bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800',
        ]"
      >
        <div class="flex items-center gap-3">
          <svg
            v-if="allAssetsHaveImages"
            class="w-6 h-6 text-green-600 dark:text-green-400"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
          </svg>
          <svg
            v-else
            class="w-6 h-6 text-yellow-600 dark:text-yellow-400"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <div>
            <p
              :class="[
                'font-medium',
                allAssetsHaveImages
                  ? 'text-green-800 dark:text-green-200'
                  : 'text-yellow-800 dark:text-yellow-200',
              ]"
            >
              {{
                allAssetsHaveImages
                  ? t('assetReview.allImagesReady')
                  : t('assetReview.missingImages', { count: assetsWithMissingImages.length })
              }}
            </p>
            <p class="text-sm text-gray-600 dark:text-gray-400">
              {{ t('assetReview.reviewHint') }}
            </p>
          </div>
        </div>
      </div>

      <!-- Tabs -->
      <div class="border-b border-gray-200 dark:border-gray-700">
        <nav class="flex gap-4">
          <button
            v-for="tab in (['person', 'scene', 'item'] as const)"
            :key="tab"
            type="button"
            :class="[
              'px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors',
              activeTab === tab
                ? 'border-primary-500 text-primary-600 dark:text-primary-400'
                : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300',
            ]"
            @click="activeTab = tab"
          >
            {{ t(`assets.types.${tab}`) }}
            <span class="ml-1 text-xs text-gray-400">
              ({{ tab === 'person' ? assets.persons.length : tab === 'scene' ? assets.scenes.length : assets.items.length }})
            </span>
          </button>
        </nav>
      </div>

      <!-- Asset Grid -->
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <div
          v-for="asset in currentAssets"
          :key="asset.id"
          class="card p-4 hover:shadow-lg transition-shadow"
        >
          <!-- Asset Header -->
          <div class="flex items-start justify-between mb-3">
            <div>
              <h4 class="font-medium text-gray-900 dark:text-white">
                {{ asset.canonical_name }}
              </h4>
              <p v-if="asset.aliases?.length" class="text-xs text-gray-500 dark:text-gray-400">
                {{ asset.aliases.join(', ') }}
              </p>
            </div>
            <div class="flex items-center gap-1">
              <span
                v-if="asset.is_global"
                class="px-2 py-0.5 text-xs bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 rounded"
              >
                {{ t('assets.filter.global') }}
              </span>
              <button
                v-else
                type="button"
                class="p-1 text-gray-400 hover:text-blue-500"
                :title="t('assetReview.promoteToGlobal')"
                @click="promoteToGlobal(asset)"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 10l7-7m0 0l7 7m-7-7v18" />
                </svg>
              </button>
            </div>
          </div>

          <!-- Images Preview -->
          <div class="grid grid-cols-3 gap-2 mb-3">
            <!-- Main Image -->
            <div
              :class="[
                'aspect-square rounded-lg overflow-hidden border-2',
                asset.main_image
                  ? 'border-gray-200 dark:border-gray-700'
                  : 'border-dashed border-yellow-400 dark:border-yellow-600 bg-yellow-50 dark:bg-yellow-900/20',
              ]"
            >
              <img
                v-if="asset.main_image"
                :src="getMediaUrl(asset.main_image)"
                :alt="asset.canonical_name"
                class="w-full h-full object-cover"
              />
              <div v-else class="w-full h-full flex items-center justify-center">
                <svg class="w-6 h-6 text-yellow-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                </svg>
              </div>
            </div>
            <!-- Angle Images (Optional) -->
            <div
              v-for="(img, idx) in [asset.angle_image_1, asset.angle_image_2]"
              :key="idx"
              class="aspect-square rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700 bg-gray-100 dark:bg-gray-800"
            >
              <img
                v-if="img"
                :src="getMediaUrl(img)"
                :alt="`${asset.canonical_name} angle ${idx + 1}`"
                class="w-full h-full object-cover"
              />
              <div v-else class="w-full h-full flex items-center justify-center">
                <span class="text-xs text-gray-400">{{ t('common.optional') }}</span>
              </div>
            </div>
          </div>

          <!-- Description -->
          <p v-if="asset.description" class="text-sm text-gray-600 dark:text-gray-300 line-clamp-2 mb-3">
            {{ asset.description }}
          </p>

          <!-- Actions -->
          <div class="flex items-center justify-between pt-2 border-t border-gray-100 dark:border-gray-700">
            <button
              type="button"
              class="text-sm text-primary-600 dark:text-primary-400 hover:underline"
              @click="openEditModal(asset)"
            >
              {{ t('common.edit') }}
            </button>
            <button
              type="button"
              class="text-sm text-red-600 dark:text-red-400 hover:underline"
              @click="handleDeleteAsset(asset)"
            >
              {{ t('common.delete') }}
            </button>
          </div>
        </div>

        <!-- Empty State -->
        <div
          v-if="currentAssets.length === 0"
          class="col-span-full text-center py-12 text-gray-500 dark:text-gray-400"
        >
          {{ t('assets.empty') }}
        </div>
      </div>

      <!-- Global Assets Suggestion -->
      <div v-if="globalAssetsForType.length > 0" class="card p-4">
        <h4 class="font-medium text-gray-900 dark:text-white mb-3">
          {{ t('assetReview.globalAssetsSuggestion') }}
        </h4>
        <div class="flex flex-wrap gap-2">
          <div
            v-for="globalAsset in globalAssetsForType"
            :key="globalAsset.id"
            class="flex items-center gap-2 px-3 py-1.5 bg-blue-50 dark:bg-blue-900/20 rounded-full"
          >
            <img
              v-if="globalAsset.main_image"
              :src="getMediaUrl(globalAsset.main_image)"
              :alt="globalAsset.canonical_name"
              class="w-6 h-6 rounded-full object-cover"
            />
            <span class="text-sm text-blue-700 dark:text-blue-300">
              {{ globalAsset.canonical_name }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- Edit Modal -->
    <Teleport to="body">
      <div
        v-if="isEditModalOpen && selectedAsset"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
        @click.self="closeEditModal"
      >
        <div class="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto m-4">
          <!-- Modal Header -->
          <div class="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
            <h3 class="text-lg font-semibold text-gray-900 dark:text-white">
              {{ t('common.edit') }}: {{ selectedAsset.canonical_name }}
            </h3>
            <button
              type="button"
              class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
              @click="closeEditModal"
            >
              <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <!-- Modal Body -->
          <div class="p-4 space-y-4">
            <!-- Basic Info -->
            <div class="grid grid-cols-2 gap-4">
              <div>
                <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  {{ t('assets.fields.name') }}
                </label>
                <input
                  v-model="selectedAsset.canonical_name"
                  type="text"
                  class="input"
                />
              </div>
              <div>
                <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  {{ t('assets.fields.aliases') }}
                </label>
                <input
                  :value="selectedAsset.aliases?.join(', ')"
                  type="text"
                  class="input"
                  @input="selectedAsset.aliases = ($event.target as HTMLInputElement).value.split(',').map(s => s.trim()).filter(Boolean)"
                />
              </div>
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                {{ t('assets.fields.description') }}
              </label>
              <textarea
                v-model="selectedAsset.description"
                rows="2"
                class="input"
              />
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                {{ t('assets.fields.baseTraits') }}
              </label>
              <textarea
                v-model="selectedAsset.base_traits"
                rows="2"
                class="input"
                placeholder="English traits for image generation prompt..."
              />
            </div>

            <!-- Images -->
            <div>
              <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                {{ t('assetReview.images') }}
              </label>
              <div class="grid grid-cols-3 gap-4">
                <!-- Main Image -->
                <div>
                  <p class="text-xs text-gray-500 dark:text-gray-400 mb-1">
                    {{ t('assets.fields.mainImage') }} *
                  </p>
                  <div
                    class="aspect-square rounded-lg border-2 border-dashed border-gray-300 dark:border-gray-600 overflow-hidden relative group"
                  >
                    <img
                      v-if="selectedAsset.main_image"
                      :src="getMediaUrl(selectedAsset.main_image)"
                      class="w-full h-full object-cover"
                    />
                    <!-- Generating overlay -->
                    <div
                      v-if="isGenerating"
                      class="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/70 z-10"
                    >
                      <div class="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-white" />
                      <span class="text-xs text-white">{{ t('assetReview.generating') }}</span>
                    </div>
                    <!-- Actions overlay -->
                    <div
                      v-else
                      :class="[
                        'absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/50 transition-opacity',
                        selectedAsset.main_image ? 'opacity-0 group-hover:opacity-100' : 'opacity-100',
                      ]"
                    >
                      <label class="btn-secondary text-xs cursor-pointer" :class="{ 'pointer-events-none opacity-50': isUploading }">
                        <input
                          type="file"
                          accept="image/*"
                          class="hidden"
                          :disabled="isUploading || isGenerating"
                          @change="handleImageUpload($event, 'main_image')"
                        />
                        {{ t('assets.actions.uploadImage') }}
                      </label>
                      <button
                        type="button"
                        class="btn-primary text-xs"
                        :disabled="isGenerating || isUploading"
                        @click="handleGenerateImage(selectedAsset, 'main_image')"
                      >
                        {{ t('assets.actions.generateImage') }}
                      </button>
                    </div>
                  </div>
                </div>

                <!-- Angle Image 1 -->
                <div>
                  <p class="text-xs text-gray-500 dark:text-gray-400 mb-1">
                    {{ t('assets.fields.angleImage1') }}
                  </p>
                  <div
                    class="aspect-square rounded-lg border-2 border-dashed border-gray-300 dark:border-gray-600 overflow-hidden relative group"
                  >
                    <img
                      v-if="selectedAsset.angle_image_1"
                      :src="getMediaUrl(selectedAsset.angle_image_1)"
                      class="w-full h-full object-cover"
                    />
                    <div
                      :class="[
                        'absolute inset-0 flex items-center justify-center bg-black/50 transition-opacity',
                        selectedAsset.angle_image_1 ? 'opacity-0 group-hover:opacity-100' : 'opacity-100',
                      ]"
                    >
                      <label class="btn-secondary text-xs cursor-pointer" :class="{ 'pointer-events-none opacity-50': isUploading }">
                        <input
                          type="file"
                          accept="image/*"
                          class="hidden"
                          :disabled="isUploading"
                          @change="handleImageUpload($event, 'angle_image_1')"
                        />
                        {{ t('common.upload') }}
                      </label>
                    </div>
                  </div>
                </div>

                <!-- Angle Image 2 -->
                <div>
                  <p class="text-xs text-gray-500 dark:text-gray-400 mb-1">
                    {{ t('assets.fields.angleImage2') }}
                  </p>
                  <div
                    class="aspect-square rounded-lg border-2 border-dashed border-gray-300 dark:border-gray-600 overflow-hidden relative group"
                  >
                    <img
                      v-if="selectedAsset.angle_image_2"
                      :src="getMediaUrl(selectedAsset.angle_image_2)"
                      class="w-full h-full object-cover"
                    />
                    <div
                      :class="[
                        'absolute inset-0 flex items-center justify-center bg-black/50 transition-opacity',
                        selectedAsset.angle_image_2 ? 'opacity-0 group-hover:opacity-100' : 'opacity-100',
                      ]"
                    >
                      <label class="btn-secondary text-xs cursor-pointer" :class="{ 'pointer-events-none opacity-50': isUploading }">
                        <input
                          type="file"
                          accept="image/*"
                          class="hidden"
                          :disabled="isUploading"
                          @change="handleImageUpload($event, 'angle_image_2')"
                        />
                        {{ t('common.upload') }}
                      </label>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- Global Toggle -->
            <div class="flex items-center gap-2">
              <input
                id="is-global"
                v-model="selectedAsset.is_global"
                type="checkbox"
                class="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
              />
              <label for="is-global" class="text-sm text-gray-700 dark:text-gray-300">
                {{ t('assets.fields.isGlobal') }}
              </label>
            </div>
          </div>

          <!-- Modal Footer -->
          <div class="flex items-center justify-end gap-3 p-4 border-t border-gray-200 dark:border-gray-700">
            <button type="button" class="btn-secondary" @click="closeEditModal">
              {{ t('common.cancel') }}
            </button>
            <button type="button" class="btn-primary" @click="saveAsset">
              {{ t('common.save') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
