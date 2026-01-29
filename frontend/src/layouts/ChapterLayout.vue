<script setup lang="ts">
import { computed, inject, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useChapterStore } from '@/stores/chapters'
import { updateChapterWorkflowStatus } from '@/api/chapters'
import { useToastStore } from '@/stores/toast'
import type { ChapterWorkflowStatus } from '@/types'

interface Step {
  key: string
  name: string
  route: string
  icon: string
  requiredStatus: ChapterWorkflowStatus
  completedStatus: ChapterWorkflowStatus
}

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const chapterStore = useChapterStore()
const toastStore = useToastStore()

const novelId = inject<ReturnType<typeof computed<string>>>('novelId')
const chapterId = computed(() => route.params.chapterId as string)

const isLoading = ref(true)
const isUpdating = ref(false)

const steps = computed<Step[]>(() => [
  {
    key: 'extraction',
    name: t('workflow.steps.extraction'),
    route: `/editor/${novelId?.value}/chapter/${chapterId.value}/extraction`,
    icon: 'M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z',
    requiredStatus: 'pending',
    completedStatus: 'characters_extracted',
  },
  {
    key: 'asset-review',
    name: t('workflow.steps.assetReview'),
    route: `/editor/${novelId?.value}/chapter/${chapterId.value}/asset-review`,
    icon: 'M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z',
    requiredStatus: 'characters_extracted',
    completedStatus: 'assets_reviewed',
  },
  {
    key: 'storyboard',
    name: t('workflow.steps.storyboard'),
    route: `/editor/${novelId?.value}/chapter/${chapterId.value}/storyboard`,
    icon: 'M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2',
    requiredStatus: 'assets_reviewed',
    completedStatus: 'storyboard_ready',
  },
  {
    key: 'studio',
    name: t('workflow.steps.studio'),
    route: `/editor/${novelId?.value}/chapter/${chapterId.value}/studio`,
    icon: 'M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z',
    requiredStatus: 'storyboard_ready',
    completedStatus: 'completed',
  },
])

const statusOrder: ChapterWorkflowStatus[] = [
  'pending',
  'characters_extracted',
  'assets_reviewed',
  'storyboard_ready',
  'generating',
  'completed',
]

function getStatusIndex(status: ChapterWorkflowStatus): number {
  return statusOrder.indexOf(status)
}

const currentStep = computed(() => {
  const path = route.path
  for (const step of steps.value) {
    if (path.includes(step.key)) {
      return step.key
    }
  }
  return 'extraction'
})

const currentStepIndex = computed(() => {
  return steps.value.findIndex(s => s.key === currentStep.value)
})

const currentStepObj = computed(() => {
  return steps.value.find(s => s.key === currentStep.value)
})

const canGoNext = computed(() => {
  const chapter = chapterStore.currentChapter
  if (!chapter || currentStepIndex.value >= steps.value.length - 1) return false

  const step = currentStepObj.value
  if (!step) return false

  // Can go to next step if current step is completed
  return getStatusIndex(chapter.workflowStatus) >= getStatusIndex(step.completedStatus)
})

const canGoPrevious = computed(() => {
  return currentStepIndex.value > 0
})

const nextStep = computed(() => {
  if (currentStepIndex.value < steps.value.length - 1) {
    return steps.value[currentStepIndex.value + 1]
  }
  return null
})

const previousStep = computed(() => {
  if (currentStepIndex.value > 0) {
    return steps.value[currentStepIndex.value - 1]
  }
  return null
})

onMounted(async () => {
  if (chapterId.value) {
    await chapterStore.fetchChapter(chapterId.value)
  }
  isLoading.value = false
})

watch(chapterId, async (newId) => {
  if (newId) {
    isLoading.value = true
    await chapterStore.fetchChapter(newId)
    isLoading.value = false
  }
})

function navigateToStep(step: Step): void {
  router.push(step.route)
}

function isStepCompleted(stepKey: string): boolean {
  const chapter = chapterStore.currentChapter
  if (!chapter) return false

  const step = steps.value.find(s => s.key === stepKey)
  if (!step) return false

  return getStatusIndex(chapter.workflowStatus) >= getStatusIndex(step.completedStatus)
}

function isStepAccessible(stepKey: string): boolean {
  const chapter = chapterStore.currentChapter
  if (!chapter) return false

  const step = steps.value.find(s => s.key === stepKey)
  if (!step) return false

  return getStatusIndex(chapter.workflowStatus) >= getStatusIndex(step.requiredStatus)
}

function isStepActive(stepKey: string): boolean {
  return currentStep.value === stepKey
}

async function goToNextStep(): Promise<void> {
  if (!nextStep.value || !canGoNext.value) return
  navigateToStep(nextStep.value)
}

async function goToPreviousStep(): Promise<void> {
  if (!previousStep.value) return
  navigateToStep(previousStep.value)
}

async function completeCurrentStep(): Promise<void> {
  const chapter = chapterStore.currentChapter
  const step = currentStepObj.value
  if (!chapter || !step) return

  // Check if already completed
  if (getStatusIndex(chapter.workflowStatus) >= getStatusIndex(step.completedStatus)) {
    // Already completed, just go to next
    await goToNextStep()
    return
  }

  // Update workflow status
  isUpdating.value = true
  try {
    await updateChapterWorkflowStatus(chapterId.value, step.completedStatus)
    await chapterStore.fetchChapter(chapterId.value)
    toastStore.success(t('workflow.stepCompleted'))

    // Navigate to next step if available
    if (nextStep.value) {
      navigateToStep(nextStep.value)
    }
  } catch (error) {
    console.error('Failed to update workflow status:', error)
    toastStore.error(t('workflow.updateFailed'))
  } finally {
    isUpdating.value = false
  }
}
</script>

<template>
  <div class="chapter-layout flex flex-col h-full">
    <!-- Chapter Header -->
    <header class="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-6 py-4">
      <div class="flex items-center justify-between">
        <div>
          <h2 class="text-xl font-semibold text-gray-900 dark:text-white">
            {{ chapterStore.currentChapter?.title || t('editor.loading') }}
          </h2>
          <p class="text-sm text-gray-500 dark:text-gray-400">
            {{ t('workflow.chapter') }} {{ chapterStore.currentChapter?.number }}
          </p>
        </div>
        <div class="text-sm text-gray-500 dark:text-gray-400">
          {{ t('workflow.status') }}:
          <span class="font-medium text-primary-600 dark:text-primary-400">
            {{ chapterStore.currentChapter?.workflowStatus }}
          </span>
        </div>
      </div>
    </header>

    <!-- Step Indicator -->
    <div class="bg-gray-50 dark:bg-gray-800/50 px-6 py-4 border-b border-gray-200 dark:border-gray-700">
      <div class="flex items-center justify-center">
        <div class="flex items-center space-x-4">
          <template v-for="(step, index) in steps" :key="step.key">
            <!-- Step -->
            <button
              type="button"
              :disabled="!isStepAccessible(step.key)"
              :class="[
                'flex items-center gap-2 px-4 py-2 rounded-lg transition-all',
                isStepActive(step.key)
                  ? 'bg-primary-600 text-white'
                  : isStepCompleted(step.key)
                    ? 'bg-green-100 dark:bg-green-600/20 text-green-600 dark:text-green-400 hover:bg-green-200 dark:hover:bg-green-600/30'
                    : isStepAccessible(step.key)
                      ? 'bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-300 dark:hover:bg-gray-600'
                      : 'bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-500 cursor-not-allowed',
              ]"
              @click="navigateToStep(step)"
            >
              <!-- Step Icon -->
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" :d="step.icon" />
              </svg>
              <span class="font-medium">{{ step.name }}</span>
              <!-- Completed Check -->
              <svg
                v-if="isStepCompleted(step.key) && !isStepActive(step.key)"
                class="w-4 h-4 text-green-600 dark:text-green-400"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
              </svg>
            </button>

            <!-- Connector -->
            <div
              v-if="index < steps.length - 1"
              :class="[
                'w-8 h-0.5 transition-colors',
                isStepCompleted(step.key) ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-600',
              ]"
            />
          </template>
        </div>
      </div>
    </div>

    <!-- Content -->
    <main class="flex-1 overflow-auto bg-gray-50 dark:bg-gray-900">
      <div v-if="isLoading" class="flex items-center justify-center h-full">
        <div class="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-primary-500" />
      </div>
      <div v-else class="h-full flex flex-col">
        <!-- Main Content -->
        <div class="flex-1 overflow-auto p-6">
          <router-view />
        </div>

        <!-- Bottom Navigation -->
        <div class="bg-white dark:bg-gray-800 border-t border-gray-200 dark:border-gray-700 px-6 py-4">
          <div class="flex items-center justify-between">
            <!-- Previous Button -->
            <button
              v-if="canGoPrevious"
              type="button"
              class="btn-secondary flex items-center gap-2"
              @click="goToPreviousStep"
            >
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
              </svg>
              {{ previousStep?.name }}
            </button>
            <div v-else />

            <!-- Complete & Next Button -->
            <div class="flex items-center gap-3">
              <button
                v-if="nextStep"
                type="button"
                :disabled="!canGoNext && isUpdating"
                :class="[
                  'flex items-center gap-2',
                  canGoNext ? 'btn-primary' : 'btn-secondary',
                ]"
                @click="canGoNext ? goToNextStep() : completeCurrentStep()"
              >
                <span v-if="isUpdating" class="animate-spin rounded-full h-4 w-4 border-t-2 border-b-2 border-white" />
                <template v-else>
                  {{ canGoNext ? t('workflow.next') : t('workflow.completeStep') }}
                  <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
                  </svg>
                </template>
              </button>
              <span v-else class="text-green-600 dark:text-green-400 font-medium flex items-center gap-2">
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                </svg>
                {{ t('workflow.completed') }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
.chapter-layout {
  height: 100%;
}
</style>
