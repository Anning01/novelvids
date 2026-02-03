<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useChapterStore } from '@/stores/chapters'
import { useToastStore } from '@/stores/toast'
import {
  createExtractionTask,
  getChapterExtractionStatus,
  retryExtractionTask,
  type ChapterExtractionStatus,
  type ExtractionTask,
  type ExtractionTaskType,
} from '@/api/extraction'
import { getAssets, type Asset } from '@/api/assets'

const { t } = useI18n()
const route = useRoute()
const chapterStore = useChapterStore()
const toastStore = useToastStore()

const novelId = computed(() => route.params.novelId as string)
const chapterId = computed(() => route.params.chapterId as string)

// 状态
const isLoading = ref(true)
const extractionStatus = ref<ChapterExtractionStatus | null>(null)
const extractedAssets = ref<{ persons: Asset[]; scenes: Asset[]; items: Asset[] }>({
  persons: [],
  scenes: [],
  items: [],
})

// 轮询控制
const pollingInterval = ref<ReturnType<typeof setInterval> | null>(null)
const POLL_INTERVAL_MS = 2000
const wasRunning = ref(false) // 追踪之前是否有任务在运行

// 计算属性
const personTask = computed(() => extractionStatus.value?.person)
const sceneTask = computed(() => extractionStatus.value?.scene)
const itemTask = computed(() => extractionStatus.value?.item)

const isAnyRunning = computed(() => {
  const tasks = [personTask.value, sceneTask.value, itemTask.value]
  return tasks.some((t) => t?.status === 'running' || t?.status === 'pending' || t?.status === 'queued')
})

const overallProgress = computed(() => extractionStatus.value?.overall_progress ?? 0)

// 获取任务状态颜色
function getTaskStatusColor(task: ExtractionTask | null | undefined): string {
  if (!task) return 'bg-gray-400'
  switch (task.status) {
    case 'completed':
      return 'bg-green-500'
    case 'running':
    case 'pending':
    case 'queued':
      return 'bg-blue-500'
    case 'failed':
      return 'bg-red-500'
    case 'cancelled':
      return 'bg-gray-500'
    default:
      return 'bg-gray-400'
  }
}

// 获取任务状态文本
function getTaskStatusText(task: ExtractionTask | null | undefined): string {
  if (!task) return t('extraction.notStarted')
  switch (task.status) {
    case 'completed':
      return t('extraction.completed')
    case 'running':
      return task.message || t('extraction.running')
    case 'pending':
    case 'queued':
      return t('extraction.pending')
    case 'failed':
      return task.error || t('extraction.failed')
    case 'cancelled':
      return t('extraction.cancelled')
    default:
      return t('extraction.notStarted')
  }
}

// 加载提取状态
async function loadExtractionStatus(): Promise<void> {
  try {
    extractionStatus.value = await getChapterExtractionStatus(chapterId.value)
  } catch (error) {
    console.error('Failed to load extraction status:', error)
  }
}

// 加载已提取的资产
async function loadExtractedAssets(): Promise<void> {
  try {
    const [persons, scenes, items] = await Promise.all([
      getAssets(novelId.value, { asset_type: 'person', page_size: 100 }),
      getAssets(novelId.value, { asset_type: 'scene', page_size: 100 }),
      getAssets(novelId.value, { asset_type: 'item', page_size: 100 }),
    ])
    extractedAssets.value = {
      persons: persons.items,
      scenes: scenes.items,
      items: items.items,
    }
  } catch (error) {
    console.error('Failed to load assets:', error)
  }
}

// 开始轮询
function startPolling(): void {
  if (pollingInterval.value) return

  wasRunning.value = true // 标记开始有任务运行

  pollingInterval.value = setInterval(async () => {
    await loadExtractionStatus()

    // 如果没有正在运行的任务，停止轮询并刷新资产
    if (!isAnyRunning.value) {
      stopPolling()
      // 只有之前有任务在运行，现在完成了，才刷新资产
      if (wasRunning.value) {
        wasRunning.value = false
        await loadExtractedAssets()
        toastStore.success(t('extraction.completed'))
      }
    }
  }, POLL_INTERVAL_MS)
}

// 停止轮询
function stopPolling(): void {
  if (pollingInterval.value) {
    clearInterval(pollingInterval.value)
    pollingInterval.value = null
  }
}

// 开始提取单个类型
async function startExtraction(taskType: ExtractionTaskType): Promise<void> {
  try {
    await createExtractionTask({
      chapter_id: chapterId.value,
      task_type: taskType,
      timeout_seconds: 600,
      max_retries: 3,
    })
    toastStore.success(t('extraction.taskSubmitted'))
    await loadExtractionStatus()
    startPolling()
  } catch (error) {
    console.error(`Failed to start ${taskType} extraction:`, error)
    toastStore.error(t('extraction.submitFailed'))
  }
}

// 开始提取所有类型
async function startAllExtraction(): Promise<void> {
  const types: ExtractionTaskType[] = ['person', 'scene', 'item']
  try {
    for (const type of types) {
      await createExtractionTask({
        chapter_id: chapterId.value,
        task_type: type,
        timeout_seconds: 600,
        max_retries: 3,
      })
    }
    toastStore.success(t('extraction.allTasksSubmitted'))
    await loadExtractionStatus()
    startPolling()
  } catch (error) {
    console.error('Failed to start extraction:', error)
    toastStore.error(t('extraction.submitFailed'))
  }
}

// 重试失败的任务
async function retryTask(taskId: string): Promise<void> {
  try {
    await retryExtractionTask(taskId)
    toastStore.success(t('extraction.retrySubmitted'))
    await loadExtractionStatus()
    startPolling()
  } catch (error) {
    console.error('Failed to retry task:', error)
    toastStore.error(t('extraction.retryFailed'))
  }
}

// 初始化
onMounted(async () => {
  isLoading.value = true
  try {
    await Promise.all([loadExtractionStatus(), loadExtractedAssets()])
    // 如果有正在运行的任务，开始轮询
    if (isAnyRunning.value) {
      startPolling()
    }
  } finally {
    isLoading.value = false
  }
})

// 清理
onUnmounted(() => {
  stopPolling()
})

// 监听章节变化
watch(chapterId, async () => {
  stopPolling()
  isLoading.value = true
  try {
    await Promise.all([loadExtractionStatus(), loadExtractedAssets()])
    if (isAnyRunning.value) {
      startPolling()
    }
  } finally {
    isLoading.value = false
  }
})
</script>

<template>
  <div class="extraction-view">
    <div v-if="isLoading" class="flex items-center justify-center py-12">
      <div class="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-primary-500" />
    </div>

    <div v-else class="space-y-6">
      <!-- 章节内容预览 -->
      <div class="card p-6">
        <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          {{ t('extraction.chapterContent') }}
        </h3>
        <div class="max-h-60 overflow-y-auto">
          <p class="text-gray-600 dark:text-gray-300 whitespace-pre-wrap text-sm leading-relaxed">
            {{ chapterStore.currentChapter?.content?.slice(0, 2000) || t('extraction.noContent') }}
            <span v-if="(chapterStore.currentChapter?.content?.length ?? 0) > 2000" class="text-gray-400">
              ...
            </span>
          </p>
        </div>
      </div>

      <!-- 提取任务状态 -->
      <div class="card p-6">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-lg font-semibold text-gray-900 dark:text-white">
            {{ t('extraction.extractionTasks') }}
          </h3>
          <button
            v-if="!isAnyRunning"
            type="button"
            class="btn-primary"
            @click="startAllExtraction"
          >
            {{ t('extraction.extractAll') }}
          </button>
          <div v-else class="flex items-center gap-2">
            <div class="animate-spin rounded-full h-5 w-5 border-t-2 border-b-2 border-primary-500" />
            <span class="text-sm text-gray-500 dark:text-gray-400">
              {{ t('extraction.processing') }} {{ overallProgress }}%
            </span>
          </div>
        </div>

        <!-- 三类提取任务 -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
          <!-- 人物提取 -->
          <div class="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-4">
            <div class="flex items-center justify-between mb-3">
              <h4 class="font-medium text-primary-600 dark:text-primary-400">
                {{ t('extraction.persons') }}
              </h4>
              <span
                :class="['w-3 h-3 rounded-full', getTaskStatusColor(personTask)]"
                :title="getTaskStatusText(personTask)"
              />
            </div>
            <p class="text-sm text-gray-500 dark:text-gray-400 mb-3">
              {{ getTaskStatusText(personTask) }}
            </p>
            <div v-if="personTask?.status === 'running'" class="mb-3">
              <div class="h-1.5 bg-gray-200 dark:bg-gray-600 rounded-full overflow-hidden">
                <div
                  class="h-full bg-primary-500 transition-all duration-300"
                  :style="{ width: `${personTask.progress}%` }"
                />
              </div>
            </div>
            <div class="flex gap-2">
              <button
                v-if="!personTask || personTask.status === 'completed'"
                type="button"
                class="btn-secondary text-xs px-2 py-1"
                :disabled="isAnyRunning"
                @click="startExtraction('person')"
              >
                {{ personTask ? t('extraction.reExtract') : t('extraction.extract') }}
              </button>
              <button
                v-if="personTask?.status === 'failed'"
                type="button"
                class="btn-secondary text-xs px-2 py-1"
                @click="retryTask(personTask.id)"
              >
                {{ t('common.retry') }}
              </button>
            </div>
          </div>

          <!-- 场景提取 -->
          <div class="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-4">
            <div class="flex items-center justify-between mb-3">
              <h4 class="font-medium text-green-600 dark:text-green-400">
                {{ t('extraction.scenes') }}
              </h4>
              <span
                :class="['w-3 h-3 rounded-full', getTaskStatusColor(sceneTask)]"
                :title="getTaskStatusText(sceneTask)"
              />
            </div>
            <p class="text-sm text-gray-500 dark:text-gray-400 mb-3">
              {{ getTaskStatusText(sceneTask) }}
            </p>
            <div v-if="sceneTask?.status === 'running'" class="mb-3">
              <div class="h-1.5 bg-gray-200 dark:bg-gray-600 rounded-full overflow-hidden">
                <div
                  class="h-full bg-green-500 transition-all duration-300"
                  :style="{ width: `${sceneTask.progress}%` }"
                />
              </div>
            </div>
            <div class="flex gap-2">
              <button
                v-if="!sceneTask || sceneTask.status === 'completed'"
                type="button"
                class="btn-secondary text-xs px-2 py-1"
                :disabled="isAnyRunning"
                @click="startExtraction('scene')"
              >
                {{ sceneTask ? t('extraction.reExtract') : t('extraction.extract') }}
              </button>
              <button
                v-if="sceneTask?.status === 'failed'"
                type="button"
                class="btn-secondary text-xs px-2 py-1"
                @click="retryTask(sceneTask.id)"
              >
                {{ t('common.retry') }}
              </button>
            </div>
          </div>

          <!-- 物品提取 -->
          <div class="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-4">
            <div class="flex items-center justify-between mb-3">
              <h4 class="font-medium text-yellow-600 dark:text-yellow-400">
                {{ t('extraction.items') }}
              </h4>
              <span
                :class="['w-3 h-3 rounded-full', getTaskStatusColor(itemTask)]"
                :title="getTaskStatusText(itemTask)"
              />
            </div>
            <p class="text-sm text-gray-500 dark:text-gray-400 mb-3">
              {{ getTaskStatusText(itemTask) }}
            </p>
            <div v-if="itemTask?.status === 'running'" class="mb-3">
              <div class="h-1.5 bg-gray-200 dark:bg-gray-600 rounded-full overflow-hidden">
                <div
                  class="h-full bg-yellow-500 transition-all duration-300"
                  :style="{ width: `${itemTask.progress}%` }"
                />
              </div>
            </div>
            <div class="flex gap-2">
              <button
                v-if="!itemTask || itemTask.status === 'completed'"
                type="button"
                class="btn-secondary text-xs px-2 py-1"
                :disabled="isAnyRunning"
                @click="startExtraction('item')"
              >
                {{ itemTask ? t('extraction.reExtract') : t('extraction.extract') }}
              </button>
              <button
                v-if="itemTask?.status === 'failed'"
                type="button"
                class="btn-secondary text-xs px-2 py-1"
                @click="retryTask(itemTask.id)"
              >
                {{ t('common.retry') }}
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 已提取的资产 -->
      <div class="card p-6">
        <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          {{ t('extraction.extractedAssets') }}
        </h3>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
          <!-- 人物列表 -->
          <div>
            <h4 class="font-medium text-primary-600 dark:text-primary-400 mb-2">
              {{ t('extraction.persons') }} ({{ extractedAssets.persons.length }})
            </h4>
            <div class="space-y-2 max-h-60 overflow-y-auto">
              <div
                v-for="asset in extractedAssets.persons"
                :key="asset.id"
                class="p-2 bg-gray-50 dark:bg-gray-700/50 rounded text-sm"
              >
                <p class="font-medium text-gray-900 dark:text-white">{{ asset.canonical_name }}</p>
                <p v-if="asset.aliases?.length" class="text-xs text-gray-500 dark:text-gray-400">
                  {{ asset.aliases.join(', ') }}
                </p>
              </div>
              <p
                v-if="extractedAssets.persons.length === 0"
                class="text-gray-500 dark:text-gray-400 text-sm"
              >
                {{ t('extraction.noEntities') }}
              </p>
            </div>
          </div>

          <!-- 场景列表 -->
          <div>
            <h4 class="font-medium text-green-600 dark:text-green-400 mb-2">
              {{ t('extraction.scenes') }} ({{ extractedAssets.scenes.length }})
            </h4>
            <div class="space-y-2 max-h-60 overflow-y-auto">
              <div
                v-for="asset in extractedAssets.scenes"
                :key="asset.id"
                class="p-2 bg-gray-50 dark:bg-gray-700/50 rounded text-sm"
              >
                <p class="font-medium text-gray-900 dark:text-white">{{ asset.canonical_name }}</p>
                <p v-if="asset.description" class="text-xs text-gray-500 dark:text-gray-400 line-clamp-2">
                  {{ asset.description }}
                </p>
              </div>
              <p
                v-if="extractedAssets.scenes.length === 0"
                class="text-gray-500 dark:text-gray-400 text-sm"
              >
                {{ t('extraction.noEntities') }}
              </p>
            </div>
          </div>

          <!-- 物品列表 -->
          <div>
            <h4 class="font-medium text-yellow-600 dark:text-yellow-400 mb-2">
              {{ t('extraction.items') }} ({{ extractedAssets.items.length }})
            </h4>
            <div class="space-y-2 max-h-60 overflow-y-auto">
              <div
                v-for="asset in extractedAssets.items"
                :key="asset.id"
                class="p-2 bg-gray-50 dark:bg-gray-700/50 rounded text-sm"
              >
                <p class="font-medium text-gray-900 dark:text-white">{{ asset.canonical_name }}</p>
                <p v-if="asset.description" class="text-xs text-gray-500 dark:text-gray-400 line-clamp-2">
                  {{ asset.description }}
                </p>
              </div>
              <p
                v-if="extractedAssets.items.length === 0"
                class="text-gray-500 dark:text-gray-400 text-sm"
              >
                {{ t('extraction.noEntities') }}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
