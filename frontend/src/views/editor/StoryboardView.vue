<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getMediaUrl } from '@/api/client'
import {
  startGenerateStoryboard,
  getTaskStatus,
  getChapterTask,
  getStoryboard,
  updateShot,
  deleteShot,
  addShot,
  getStoryboardPrompts,
  type Shot,
  type StoryboardResponse,
  type StoryboardTask,
  type ShotPrompt,
  SHOT_SIZES,
  CAMERA_ANGLES,
  CAMERA_MOVEMENTS,
  VIDEO_STYLES,
  MOODS,
  LIGHTING_STYLES,
  ASPECT_RATIOS,
  TARGET_PLATFORMS,
} from '@/api/storyboard'
import { getAssets, type Asset } from '@/api/assets'
import { getChapter } from '@/api/chapters'
import type { ChapterDetail } from '@/types'

const { t } = useI18n()
const route = useRoute()

// Route params
const novelId = computed(() => route.params.novelId as string)
const chapterId = computed(() => route.params.chapterId as string)

// State
const isLoading = ref(true)
const isSaving = ref(false)
const chapter = ref<ChapterDetail | null>(null)
const storyboard = ref<StoryboardResponse | null>(null)
const assets = ref<Asset[]>([])
const error = ref<string | null>(null)

// Task state
const currentTask = ref<StoryboardTask | null>(null)
const pollingInterval = ref<number | null>(null)

// Edit modal state
const showEditModal = ref(false)
const editingShot = ref<Shot | null>(null)
const editForm = ref<Partial<Shot>>({})

// Generate settings
const showGenerateSettings = ref(false)
const generateSettings = ref({
  max_shot_duration: 8,
  target_platform: 'veo' as 'veo' | 'vidu' | 'kling' | 'sora',
  style_preset: 'cinematic',
  aspect_ratio: '16:9',
  include_audio: true,
})

// Prompts modal
const showPromptsModal = ref(false)
const prompts = ref<ShotPrompt[]>([])
const selectedPlatform = ref<'veo' | 'vidu' | 'kling' | 'sora'>('veo')

// Asset selector
const showAssetSelector = ref(false)
const assetSelectorField = ref<'subject' | 'environment'>('subject')
const assetSelectorTypes = ref<string[]>(['person', 'scene', 'item'])

// Computed
const shots = computed(() => storyboard.value?.shots || [])
const isGenerating = computed(() =>
  currentTask.value?.status === 'pending' ||
  currentTask.value?.status === 'running' ||
  currentTask.value?.status === 'queued'
)
const taskProgress = computed(() => currentTask.value?.progress || 0)
const taskMessage = computed(() => currentTask.value?.message || '')

// Methods
async function loadData() {
  isLoading.value = true
  error.value = null

  try {
    // Load chapter info
    chapter.value = await getChapter(chapterId.value)

    // Load assets
    const assetsResponse = await getAssets(novelId.value, { page_size: 100 })
    assets.value = assetsResponse.items

    // Load existing storyboard (returns empty array if none)
    storyboard.value = await getStoryboard(chapterId.value)

    // Check for in-progress task (resume polling if found)
    const task = await getChapterTask(chapterId.value)
    if (task) {
      const isInProgress = task.status === 'pending' || task.status === 'running' || task.status === 'queued'
      // Only resume polling if task was created within the last 10 minutes
      const taskAge = Date.now() - new Date(task.created_at).getTime()
      const isRecent = taskAge < 10 * 60 * 1000

      if (isInProgress && isRecent) {
        currentTask.value = task
        startPolling()
      }
    }
  } catch (e: any) {
    error.value = e.message || 'Failed to load data'
  } finally {
    isLoading.value = false
  }
}

async function handleGenerateStoryboard() {
  error.value = null

  try {
    // Start generation task
    const task = await startGenerateStoryboard(chapterId.value, generateSettings.value)
    currentTask.value = task
    showGenerateSettings.value = false

    // Start polling
    startPolling()
  } catch (e: any) {
    error.value = e.message || t('storyboard.generateFailed')
  }
}

function startPolling() {
  if (pollingInterval.value) return

  pollingInterval.value = window.setInterval(async () => {
    if (!currentTask.value) {
      stopPolling()
      return
    }

    try {
      const task = await getTaskStatus(currentTask.value.id)
      currentTask.value = task

      if (task.status === 'completed') {
        stopPolling()
        // Reload storyboard data
        storyboard.value = await getStoryboard(chapterId.value)
      } else if (task.status === 'failed' || task.status === 'cancelled') {
        stopPolling()
        error.value = task.error || t('storyboard.generateFailed')
      }
    } catch (e: any) {
      stopPolling()
      error.value = e.message
    }
  }, 1500)
}

function stopPolling() {
  if (pollingInterval.value) {
    clearInterval(pollingInterval.value)
    pollingInterval.value = null
  }
}

function openEditModal(shot: Shot) {
  editingShot.value = shot
  editForm.value = JSON.parse(JSON.stringify(shot))
  showEditModal.value = true
}

async function handleSaveShot() {
  if (!editingShot.value || !editForm.value) return

  isSaving.value = true
  try {
    const updated = await updateShot(
      chapterId.value,
      editingShot.value.sequence,
      editForm.value as Parameters<typeof updateShot>[2]
    )

    // Update local state
    const index = shots.value.findIndex(s => s.sequence === editingShot.value!.sequence)
    if (index !== -1 && storyboard.value) {
      storyboard.value.shots[index] = updated
    }

    showEditModal.value = false
    editingShot.value = null
  } catch (e: any) {
    error.value = e.message || 'Failed to save shot'
  } finally {
    isSaving.value = false
  }
}

async function handleDeleteShot(shot: Shot) {
  if (!confirm(t('storyboard.shotCard.deleteConfirm'))) return

  try {
    await deleteShot(chapterId.value, shot.sequence)

    // Update local state
    if (storyboard.value) {
      storyboard.value.shots = storyboard.value.shots.filter(s => s.sequence !== shot.sequence)
      // Re-sequence
      storyboard.value.shots.forEach((s, i) => {
        s.sequence = i + 1
      })
      storyboard.value.shot_count = storyboard.value.shots.length
      storyboard.value.total_duration = storyboard.value.shots.reduce(
        (sum, s) => sum + (s.technical?.duration || 0),
        0
      )
    }
  } catch (e: any) {
    error.value = e.message || 'Failed to delete shot'
  }
}

async function handleAddShot(afterSequence?: number) {
  const newShot: Partial<Shot> = {
    name: `New Shot`,
    description_cn: '新镜头',
    camera: {
      shot_size: 'medium_shot',
      camera_angle: 'eye_level',
      camera_movement: 'static',
      movement_speed: 'smooth',
      lens_type: 'normal',
      depth_of_field: 'normal',
      focus_target: null,
    },
    subject: {
      subject_type: 'person',
      subject_description: '',
      asset_refs: [],
      action: '',
      action_intensity: 'normal',
      emotion: null,
      body_language: null,
    },
    environment: {
      location: '',
      scene_asset_ref: null,
      time_of_day: 'day',
      weather: null,
      lighting: 'natural',
      lighting_details: null,
      atmosphere_elements: [],
    },
    style: {
      video_style: 'cinematic',
      mood: 'peaceful',
      color_grading: null,
      film_grain: false,
      contrast: 'normal',
      saturation: 'normal',
    },
    audio: {
      dialogue: null,
      dialogue_speaker: null,
      dialogue_tone: null,
      sound_effects: [],
      ambient_sounds: [],
      background_music: null,
      music_volume: 'normal',
    },
    technical: {
      duration: 6,
      aspect_ratio: '16:9',
      motion_speed: 'normal',
      resolution: '1080p',
      fps: 24,
    },
    negative: {
      avoid_elements: [],
      avoid_artifacts: true,
      avoid_text: true,
    },
    reference_images: [],
    start_frame: null,
    end_frame: null,
    transition_in: 'cut',
    transition_out: 'cut',
  }

  try {
    const added = await addShot(chapterId.value, newShot, afterSequence)

    // Update local state
    if (storyboard.value) {
      if (afterSequence !== undefined) {
        storyboard.value.shots.splice(afterSequence, 0, added)
      } else {
        storyboard.value.shots.push(added)
      }
      // Re-sequence
      storyboard.value.shots.forEach((s, i) => {
        s.sequence = i + 1
      })
      storyboard.value.shot_count = storyboard.value.shots.length
    }

    // Open edit modal for new shot
    openEditModal(added)
  } catch (e: any) {
    error.value = e.message || 'Failed to add shot'
  }
}

async function handleViewPrompts() {
  try {
    const response = await getStoryboardPrompts(chapterId.value, selectedPlatform.value)
    prompts.value = response.prompts
    showPromptsModal.value = true
  } catch (e: any) {
    error.value = e.message || 'Failed to get prompts'
  }
}

function copyPrompt(text: string) {
  navigator.clipboard.writeText(text)
}

function copyAllPrompts() {
  const allPrompts = prompts.value
    .map(p => `--- Shot ${p.sequence} ---\n${p.prompt}\n\nNegative: ${p.negative_prompt}`)
    .join('\n\n')
  navigator.clipboard.writeText(allPrompts)
}

function getAssetById(id: string): Asset | undefined {
  return assets.value.find(a => a.id === id)
}

function getAssetName(id: string): string {
  const asset = getAssetById(id)
  return asset?.canonical_name || id
}

function openAssetSelector(field: 'subject' | 'environment', types: string[]) {
  assetSelectorField.value = field
  assetSelectorTypes.value = types
  showAssetSelector.value = true
}

function selectAsset(asset: Asset) {
  if (!editForm.value) return

  if (assetSelectorField.value === 'subject') {
    if (!editForm.value.subject) {
      editForm.value.subject = {} as any
    }
    if (!editForm.value.subject!.asset_refs) {
      editForm.value.subject!.asset_refs = []
    }
    if (!editForm.value.subject!.asset_refs.includes(asset.id)) {
      editForm.value.subject!.asset_refs.push(asset.id)
    }
    // Auto-fill description if empty
    if (!editForm.value.subject!.subject_description && asset.base_traits) {
      editForm.value.subject!.subject_description = asset.base_traits
    }
  } else if (assetSelectorField.value === 'environment') {
    if (!editForm.value.environment) {
      editForm.value.environment = {} as any
    }
    editForm.value.environment!.scene_asset_ref = asset.id
    // Auto-fill location if empty
    if (!editForm.value.environment!.location && asset.base_traits) {
      editForm.value.environment!.location = asset.base_traits
    }
  }

  showAssetSelector.value = false
}

function removeAssetRef(id: string) {
  if (!editForm.value?.subject?.asset_refs) return
  editForm.value.subject.asset_refs = editForm.value.subject.asset_refs.filter(ref => ref !== id)
}

function formatDuration(seconds: number): string {
  return `${seconds.toFixed(1)}s`
}

// Lifecycle
onMounted(() => {
  loadData()
})

onUnmounted(() => {
  stopPolling()
})

watch([novelId, chapterId], () => {
  stopPolling()
  loadData()
})
</script>

<template>
  <div class="storyboard-view h-full flex flex-col">
    <!-- Header -->
    <div class="flex-none p-4 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-xl font-semibold text-gray-900 dark:text-white">
            {{ t('storyboard.title') }}
          </h1>
          <p v-if="chapter" class="text-sm text-gray-500 dark:text-gray-400">
            {{ t('chapters.chapter', { number: chapter.number }) }} - {{ chapter.title }}
          </p>
        </div>

        <div class="flex items-center gap-3">
          <!-- Stats -->
          <div v-if="storyboard" class="flex items-center gap-4 text-sm text-gray-500 dark:text-gray-400">
            <span>{{ t('storyboard.shotCount') }}: {{ storyboard.shot_count }}</span>
            <span>{{ t('storyboard.totalDuration') }}: {{ formatDuration(storyboard.total_duration) }}</span>
          </div>

          <!-- Actions -->
          <button
            v-if="storyboard"
            type="button"
            class="btn-secondary"
            @click="handleViewPrompts"
          >
            {{ t('storyboard.prompts.title') }}
          </button>

          <button
            type="button"
            class="btn-primary"
            :disabled="isGenerating"
            @click="showGenerateSettings = true"
          >
            <span v-if="isGenerating" class="flex items-center gap-2">
              <span class="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
              {{ t('storyboard.generating') }}
            </span>
            <span v-else>
              {{ storyboard ? t('storyboard.regenerate') : t('storyboard.generate') }}
            </span>
          </button>
        </div>
      </div>
    </div>

    <!-- Error Message -->
    <div v-if="error" class="flex-none p-4 bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400">
      {{ error }}
      <button class="ml-2 underline" @click="error = null">{{ t('common.close') }}</button>
    </div>

    <!-- Generation Progress -->
    <div v-if="isGenerating" class="flex-none p-4 bg-blue-50 dark:bg-blue-900/20">
      <div class="flex items-center gap-4">
        <div class="animate-spin h-5 w-5 border-2 border-blue-600 border-t-transparent rounded-full" />
        <div class="flex-1">
          <div class="flex items-center justify-between mb-1">
            <span class="text-sm font-medium text-blue-700 dark:text-blue-300">
              {{ taskMessage || t('storyboard.generating') }}
            </span>
            <span class="text-sm text-blue-600 dark:text-blue-400">{{ taskProgress }}%</span>
          </div>
          <div class="w-full bg-blue-200 dark:bg-blue-800 rounded-full h-2">
            <div
              class="bg-blue-600 h-2 rounded-full transition-all duration-300"
              :style="{ width: `${taskProgress}%` }"
            />
          </div>
        </div>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="isLoading" class="flex-1 flex items-center justify-center">
      <div class="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-primary-500" />
    </div>

    <!-- Empty State -->
    <div
      v-else-if="!isGenerating && (!storyboard || shots.length === 0)"
      class="flex-1 flex flex-col items-center justify-center text-gray-500 dark:text-gray-400"
    >
      <svg class="w-16 h-16 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 4v16M17 4v16M3 8h4m10 0h4M3 12h18M3 16h4m10 0h4M4 20h16a1 1 0 001-1V5a1 1 0 00-1-1H4a1 1 0 00-1 1v14a1 1 0 001 1z" />
      </svg>
      <p class="text-lg mb-2">{{ t('storyboard.noStoryboard') }}</p>
      <p class="text-sm mb-4">{{ t('storyboard.noStoryboardHint') }}</p>
      <button type="button" class="btn-primary" @click="showGenerateSettings = true">
        {{ t('storyboard.generate') }}
      </button>
    </div>

    <!-- Shots List -->
    <div v-else class="flex-1 overflow-auto p-4">
      <div class="space-y-4">
        <div
          v-for="shot in shots"
          :key="shot.sequence"
          class="card p-4 hover:shadow-md transition-shadow"
        >
          <div class="flex gap-4">
            <!-- Thumbnail -->
            <div class="flex-none w-48">
              <div class="aspect-video bg-gray-100 dark:bg-gray-700 rounded-lg overflow-hidden flex items-center justify-center">
                <img
                  v-if="shot.start_frame"
                  :src="getMediaUrl(shot.start_frame)"
                  class="w-full h-full object-cover"
                  alt=""
                />
                <svg v-else class="w-12 h-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
              </div>
              <div class="mt-2 text-center">
                <span class="text-sm font-medium text-gray-700 dark:text-gray-300">
                  {{ t('storyboard.shotCard.title', { sequence: shot.sequence }) }}
                </span>
                <span class="ml-2 text-xs text-gray-500">
                  {{ formatDuration(shot.technical?.duration || 0) }}
                </span>
              </div>
            </div>

            <!-- Content -->
            <div class="flex-1 min-w-0">
              <!-- Shot Name & Description -->
              <div class="mb-3">
                <h3 v-if="shot.name" class="font-medium text-gray-900 dark:text-white">
                  {{ shot.name }}
                </h3>
                <p class="text-sm text-gray-600 dark:text-gray-300">
                  {{ shot.description_cn }}
                </p>
              </div>

              <!-- Camera & Style Tags -->
              <div class="flex flex-wrap gap-2 mb-3">
                <span class="tag tag-blue">
                  {{ t(`storyboard.shotSizes.${shot.camera?.shot_size}`) || shot.camera?.shot_size }}
                </span>
                <span v-if="shot.camera?.camera_movement !== 'static'" class="tag tag-purple">
                  {{ t(`storyboard.cameraMovements.${shot.camera?.camera_movement}`) || shot.camera?.camera_movement }}
                </span>
                <span class="tag tag-green">
                  {{ t(`storyboard.moods.${shot.style?.mood}`) || shot.style?.mood }}
                </span>
                <span v-if="shot.audio?.dialogue" class="tag tag-yellow">
                  🎤 {{ t('storyboard.audio.dialogue') }}
                </span>
              </div>

              <!-- Linked Assets -->
              <div class="flex flex-wrap gap-2 mb-3">
                <template v-if="shot.subject?.asset_refs?.length">
                  <span
                    v-for="assetId in shot.subject.asset_refs"
                    :key="assetId"
                    class="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300"
                  >
                    <img
                      v-if="getAssetById(assetId)?.main_image"
                      :src="getMediaUrl(getAssetById(assetId)?.main_image)"
                      class="w-4 h-4 rounded-full object-cover"
                      alt=""
                    />
                    {{ getAssetName(assetId) }}
                  </span>
                </template>
                <span v-if="shot.environment?.scene_asset_ref" class="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300">
                  🏞️ {{ getAssetName(shot.environment.scene_asset_ref) }}
                </span>
              </div>

              <!-- Source Text Preview -->
              <div v-if="shot.source_text" class="text-xs text-gray-400 dark:text-gray-500 line-clamp-2 italic">
                "{{ shot.source_text }}"
              </div>
            </div>

            <!-- Actions -->
            <div class="flex-none flex flex-col gap-2">
              <button
                type="button"
                class="btn-secondary btn-sm"
                @click="openEditModal(shot)"
              >
                {{ t('storyboard.shotCard.edit') }}
              </button>
              <button
                type="button"
                class="btn-secondary btn-sm text-red-600 dark:text-red-400"
                @click="handleDeleteShot(shot)"
              >
                {{ t('storyboard.shotCard.delete') }}
              </button>
              <button
                type="button"
                class="btn-secondary btn-sm text-xs"
                @click="handleAddShot(shot.sequence)"
              >
                + {{ t('storyboard.shotCard.addAfter') }}
              </button>
            </div>
          </div>
        </div>

        <!-- Add Shot Button -->
        <button
          type="button"
          class="w-full py-4 border-2 border-dashed border-gray-300 dark:border-gray-600 rounded-lg text-gray-500 dark:text-gray-400 hover:border-primary-500 hover:text-primary-500 transition-colors"
          @click="handleAddShot()"
        >
          + {{ t('chapters.addChapter') }}
        </button>
      </div>
    </div>

    <!-- Generate Settings Modal -->
    <Teleport to="body">
      <div v-if="showGenerateSettings" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50" @click.self="showGenerateSettings = false">
        <div class="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-lg mx-4">
          <div class="p-4 border-b border-gray-200 dark:border-gray-700">
            <h2 class="text-lg font-semibold text-gray-900 dark:text-white">
              {{ t('storyboard.settings.title') }}
            </h2>
          </div>

          <div class="p-4 space-y-4">
            <!-- Target Platform -->
            <div>
              <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                {{ t('storyboard.settings.platform') }}
              </label>
              <select v-model="generateSettings.target_platform" class="input w-full">
                <option v-for="p in TARGET_PLATFORMS" :key="p.value" :value="p.value">
                  {{ p.label }} - {{ p.description }}
                </option>
              </select>
            </div>

            <!-- Max Duration -->
            <div>
              <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                {{ t('storyboard.settings.maxDuration') }} ({{ generateSettings.max_shot_duration }}s)
              </label>
              <input
                v-model.number="generateSettings.max_shot_duration"
                type="range"
                min="4"
                max="15"
                step="1"
                class="w-full"
              />
            </div>

            <!-- Style Preset -->
            <div>
              <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                {{ t('storyboard.settings.style') }}
              </label>
              <select v-model="generateSettings.style_preset" class="input w-full">
                <option v-for="s in VIDEO_STYLES" :key="s.value" :value="s.value">
                  {{ s.label }}
                </option>
              </select>
            </div>

            <!-- Aspect Ratio -->
            <div>
              <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                {{ t('storyboard.settings.aspectRatio') }}
              </label>
              <select v-model="generateSettings.aspect_ratio" class="input w-full">
                <option v-for="ar in ASPECT_RATIOS" :key="ar.value" :value="ar.value">
                  {{ ar.label }}
                </option>
              </select>
            </div>

            <!-- Include Audio -->
            <div class="flex items-center gap-2">
              <input
                id="include-audio"
                v-model="generateSettings.include_audio"
                type="checkbox"
                class="rounded"
              />
              <label for="include-audio" class="text-sm text-gray-700 dark:text-gray-300">
                {{ t('storyboard.settings.includeAudio') }}
              </label>
            </div>
          </div>

          <div class="p-4 border-t border-gray-200 dark:border-gray-700 flex justify-end gap-3">
            <button type="button" class="btn-secondary" @click="showGenerateSettings = false">
              {{ t('common.cancel') }}
            </button>
            <button
              type="button"
              class="btn-primary"
              :disabled="isGenerating"
              @click="handleGenerateStoryboard"
            >
              {{ t('storyboard.generate') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Edit Shot Modal -->
    <Teleport to="body">
      <div v-if="showEditModal && editForm" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50" @click.self="showEditModal = false">
        <div class="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-4xl mx-4 max-h-[90vh] overflow-hidden flex flex-col">
          <div class="flex-none p-4 border-b border-gray-200 dark:border-gray-700">
            <h2 class="text-lg font-semibold text-gray-900 dark:text-white">
              {{ t('storyboard.shotCard.edit') }} - {{ t('storyboard.shotCard.title', { sequence: editingShot?.sequence }) }}
            </h2>
          </div>

          <div class="flex-1 overflow-auto p-4">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
              <!-- Basic Info -->
              <div class="space-y-4">
                <h3 class="font-medium text-gray-900 dark:text-white border-b pb-2">基础信息</h3>

                <div>
                  <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    {{ t('storyboard.shotCard.name') }}
                  </label>
                  <input v-model="editForm.name" type="text" class="input w-full" />
                </div>

                <div>
                  <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    {{ t('storyboard.shotCard.description') }}
                  </label>
                  <textarea v-model="editForm.description_cn" rows="2" class="input w-full" />
                </div>

                <div>
                  <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    {{ t('storyboard.technical.duration') }} (s)
                  </label>
                  <input
                    v-model.number="editForm.technical!.duration"
                    type="number"
                    min="2"
                    max="15"
                    step="0.5"
                    class="input w-full"
                  />
                </div>
              </div>

              <!-- Camera Settings -->
              <div class="space-y-4">
                <h3 class="font-medium text-gray-900 dark:text-white border-b pb-2">
                  {{ t('storyboard.camera.title') }}
                </h3>

                <div>
                  <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    {{ t('storyboard.camera.shotSize') }}
                  </label>
                  <select v-model="editForm.camera!.shot_size" class="input w-full">
                    <option v-for="s in SHOT_SIZES" :key="s.value" :value="s.value">
                      {{ s.label }} ({{ s.labelEn }})
                    </option>
                  </select>
                </div>

                <div>
                  <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    {{ t('storyboard.camera.cameraAngle') }}
                  </label>
                  <select v-model="editForm.camera!.camera_angle" class="input w-full">
                    <option v-for="a in CAMERA_ANGLES" :key="a.value" :value="a.value">
                      {{ a.label }} ({{ a.labelEn }})
                    </option>
                  </select>
                </div>

                <div>
                  <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    {{ t('storyboard.camera.cameraMovement') }}
                  </label>
                  <select v-model="editForm.camera!.camera_movement" class="input w-full">
                    <option v-for="m in CAMERA_MOVEMENTS" :key="m.value" :value="m.value">
                      {{ m.label }} ({{ m.labelEn }})
                    </option>
                  </select>
                </div>
              </div>

              <!-- Subject & Assets -->
              <div class="space-y-4">
                <h3 class="font-medium text-gray-900 dark:text-white border-b pb-2">
                  {{ t('storyboard.subject.title') }}
                </h3>

                <div>
                  <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    {{ t('storyboard.subject.linkedAssets') }}
                  </label>
                  <div class="flex flex-wrap gap-2 mb-2">
                    <span
                      v-for="assetId in editForm.subject?.asset_refs || []"
                      :key="assetId"
                      class="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300"
                    >
                      {{ getAssetName(assetId) }}
                      <button type="button" class="hover:text-red-500" @click="removeAssetRef(assetId)">×</button>
                    </span>
                  </div>
                  <button
                    type="button"
                    class="btn-secondary btn-sm"
                    @click="openAssetSelector('subject', ['person', 'item'])"
                  >
                    + 添加人物/物品
                  </button>
                </div>

                <div>
                  <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    {{ t('storyboard.subject.subjectDescription') }} (English)
                  </label>
                  <textarea v-model="editForm.subject!.subject_description" rows="2" class="input w-full" placeholder="e.g., A young woman with long black hair wearing a red dress" />
                </div>

                <div>
                  <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    {{ t('storyboard.subject.action') }} (English)
                  </label>
                  <input v-model="editForm.subject!.action" type="text" class="input w-full" placeholder="e.g., walking slowly towards the window" />
                </div>

                <div>
                  <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    {{ t('storyboard.subject.emotion') }}
                  </label>
                  <input v-model="editForm.subject!.emotion" type="text" class="input w-full" placeholder="e.g., subtle sadness, thoughtful expression" />
                </div>
              </div>

              <!-- Environment -->
              <div class="space-y-4">
                <h3 class="font-medium text-gray-900 dark:text-white border-b pb-2">
                  {{ t('storyboard.environment.title') }}
                </h3>

                <div>
                  <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    场景资产
                  </label>
                  <div class="flex items-center gap-2">
                    <span v-if="editForm.environment?.scene_asset_ref" class="px-2 py-1 rounded bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 text-sm">
                      {{ getAssetName(editForm.environment.scene_asset_ref) }}
                    </span>
                    <button
                      type="button"
                      class="btn-secondary btn-sm"
                      @click="openAssetSelector('environment', ['scene'])"
                    >
                      {{ editForm.environment?.scene_asset_ref ? '更换' : '+ 选择场景' }}
                    </button>
                  </div>
                </div>

                <div>
                  <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    {{ t('storyboard.environment.location') }} (English)
                  </label>
                  <textarea v-model="editForm.environment!.location" rows="2" class="input w-full" placeholder="e.g., A cozy living room with vintage furniture and warm lighting" />
                </div>

                <div class="grid grid-cols-2 gap-4">
                  <div>
                    <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                      {{ t('storyboard.environment.timeOfDay') }}
                    </label>
                    <select v-model="editForm.environment!.time_of_day" class="input w-full">
                      <option value="dawn">黎明</option>
                      <option value="morning">早晨</option>
                      <option value="noon">中午</option>
                      <option value="afternoon">下午</option>
                      <option value="dusk">黄昏</option>
                      <option value="night">夜晚</option>
                    </select>
                  </div>
                  <div>
                    <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                      {{ t('storyboard.environment.lighting') }}
                    </label>
                    <select v-model="editForm.environment!.lighting" class="input w-full">
                      <option v-for="l in LIGHTING_STYLES" :key="l.value" :value="l.value">
                        {{ l.label }}
                      </option>
                    </select>
                  </div>
                </div>
              </div>

              <!-- Style -->
              <div class="space-y-4">
                <h3 class="font-medium text-gray-900 dark:text-white border-b pb-2">
                  {{ t('storyboard.style.title') }}
                </h3>

                <div class="grid grid-cols-2 gap-4">
                  <div>
                    <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                      {{ t('storyboard.style.videoStyle') }}
                    </label>
                    <select v-model="editForm.style!.video_style" class="input w-full">
                      <option v-for="s in VIDEO_STYLES" :key="s.value" :value="s.value">
                        {{ s.label }}
                      </option>
                    </select>
                  </div>
                  <div>
                    <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                      {{ t('storyboard.style.mood') }}
                    </label>
                    <select v-model="editForm.style!.mood" class="input w-full">
                      <option v-for="m in MOODS" :key="m.value" :value="m.value">
                        {{ m.label }}
                      </option>
                    </select>
                  </div>
                </div>

                <div>
                  <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    {{ t('storyboard.style.colorGrading') }}
                  </label>
                  <input v-model="editForm.style!.color_grading" type="text" class="input w-full" placeholder="e.g., teal-orange, warm, desaturated" />
                </div>
              </div>

              <!-- Audio -->
              <div class="space-y-4">
                <h3 class="font-medium text-gray-900 dark:text-white border-b pb-2">
                  {{ t('storyboard.audio.title') }}
                </h3>

                <div>
                  <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    {{ t('storyboard.audio.dialogue') }}
                  </label>
                  <textarea v-model="editForm.audio!.dialogue" rows="2" class="input w-full" placeholder="角色对话内容..." />
                </div>

                <div class="grid grid-cols-2 gap-4">
                  <div>
                    <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                      {{ t('storyboard.audio.dialogueSpeaker') }}
                    </label>
                    <input v-model="editForm.audio!.dialogue_speaker" type="text" class="input w-full" />
                  </div>
                  <div>
                    <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                      {{ t('storyboard.audio.dialogueTone') }}
                    </label>
                    <select v-model="editForm.audio!.dialogue_tone" class="input w-full">
                      <option value="">-</option>
                      <option value="whisper">耳语</option>
                      <option value="normal">正常</option>
                      <option value="shout">喊叫</option>
                      <option value="emotional">情绪化</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    {{ t('storyboard.audio.backgroundMusic') }}
                  </label>
                  <input v-model="editForm.audio!.background_music" type="text" class="input w-full" placeholder="e.g., soft piano melody, tense orchestral" />
                </div>
              </div>
            </div>
          </div>

          <div class="flex-none p-4 border-t border-gray-200 dark:border-gray-700 flex justify-end gap-3">
            <button type="button" class="btn-secondary" @click="showEditModal = false">
              {{ t('common.cancel') }}
            </button>
            <button
              type="button"
              class="btn-primary"
              :disabled="isSaving"
              @click="handleSaveShot"
            >
              {{ t('common.save') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Asset Selector Modal -->
    <Teleport to="body">
      <div v-if="showAssetSelector" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50" @click.self="showAssetSelector = false">
        <div class="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-2xl mx-4 max-h-[80vh] overflow-hidden flex flex-col">
          <div class="flex-none p-4 border-b border-gray-200 dark:border-gray-700">
            <h2 class="text-lg font-semibold text-gray-900 dark:text-white">
              选择资产
            </h2>
          </div>

          <div class="flex-1 overflow-auto p-4">
            <div class="grid grid-cols-2 sm:grid-cols-3 gap-4">
              <template v-for="asset in assets.filter(a => assetSelectorTypes.includes(a.asset_type))" :key="asset.id">
                <button
                  type="button"
                  class="text-left p-3 rounded-lg border border-gray-200 dark:border-gray-700 hover:border-primary-500 hover:bg-primary-50 dark:hover:bg-primary-900/20 transition-colors"
                  @click="selectAsset(asset)"
                >
                  <div class="flex items-center gap-3">
                    <div class="w-12 h-12 rounded-lg bg-gray-100 dark:bg-gray-700 overflow-hidden flex-none">
                      <img
                        v-if="asset.main_image"
                        :src="getMediaUrl(asset.main_image)"
                        class="w-full h-full object-cover"
                        alt=""
                      />
                      <div v-else class="w-full h-full flex items-center justify-center text-gray-400">
                        <span v-if="asset.asset_type === 'person'">👤</span>
                        <span v-else-if="asset.asset_type === 'scene'">🏞️</span>
                        <span v-else>📦</span>
                      </div>
                    </div>
                    <div class="min-w-0">
                      <div class="font-medium text-gray-900 dark:text-white truncate">
                        {{ asset.canonical_name }}
                      </div>
                      <div class="text-xs text-gray-500">
                        {{ t(`assets.types.${asset.asset_type}`) }}
                      </div>
                    </div>
                  </div>
                </button>
              </template>
            </div>

            <div v-if="assets.filter(a => assetSelectorTypes.includes(a.asset_type)).length === 0" class="text-center py-8 text-gray-500">
              暂无可用资产
            </div>
          </div>

          <div class="flex-none p-4 border-t border-gray-200 dark:border-gray-700">
            <button type="button" class="btn-secondary w-full" @click="showAssetSelector = false">
              {{ t('common.cancel') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Prompts Modal -->
    <Teleport to="body">
      <div v-if="showPromptsModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50" @click.self="showPromptsModal = false">
        <div class="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-4xl mx-4 max-h-[90vh] overflow-hidden flex flex-col">
          <div class="flex-none p-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
            <h2 class="text-lg font-semibold text-gray-900 dark:text-white">
              {{ t('storyboard.prompts.title') }}
            </h2>
            <div class="flex items-center gap-3">
              <select v-model="selectedPlatform" class="input" @change="handleViewPrompts">
                <option v-for="p in TARGET_PLATFORMS" :key="p.value" :value="p.value">
                  {{ p.label }}
                </option>
              </select>
              <button type="button" class="btn-secondary btn-sm" @click="copyAllPrompts">
                {{ t('storyboard.prompts.copyAll') }}
              </button>
            </div>
          </div>

          <div class="flex-1 overflow-auto p-4 space-y-4">
            <div
              v-for="prompt in prompts"
              :key="prompt.sequence"
              class="p-4 rounded-lg bg-gray-50 dark:bg-gray-900"
            >
              <div class="flex items-center justify-between mb-2">
                <span class="font-medium text-gray-900 dark:text-white">
                  {{ t('storyboard.shotCard.title', { sequence: prompt.sequence }) }}
                </span>
                <button
                  type="button"
                  class="text-sm text-primary-600 hover:text-primary-700"
                  @click="copyPrompt(prompt.prompt)"
                >
                  {{ t('storyboard.prompts.copy') }}
                </button>
              </div>
              <div class="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap font-mono bg-white dark:bg-gray-800 p-3 rounded border">
                {{ prompt.prompt }}
              </div>
              <div v-if="prompt.negative_prompt" class="mt-2">
                <span class="text-xs text-gray-500">Negative:</span>
                <div class="text-xs text-gray-500 font-mono">
                  {{ prompt.negative_prompt }}
                </div>
              </div>
            </div>
          </div>

          <div class="flex-none p-4 border-t border-gray-200 dark:border-gray-700">
            <button type="button" class="btn-secondary w-full" @click="showPromptsModal = false">
              {{ t('common.close') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.tag {
  @apply inline-flex items-center px-2 py-0.5 rounded text-xs font-medium;
}
.tag-blue {
  @apply bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300;
}
.tag-purple {
  @apply bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300;
}
.tag-green {
  @apply bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300;
}
.tag-yellow {
  @apply bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-300;
}
.btn-sm {
  @apply px-2 py-1 text-sm;
}
</style>
