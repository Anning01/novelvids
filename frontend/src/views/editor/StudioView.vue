<script setup lang="ts">
/**
 * StudioView - Video Composition Studio
 *
 * The final step in the chapter workflow where users:
 * 1. View storyboard shots in a left sidebar (with CRUD)
 * 2. Generate video clips for each shot (with progress tracking)
 * 3. Pick the best video version for each shot
 * 4. Arrange clips on a timeline via drag-and-drop
 * 5. Compose the final video
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useToastStore } from '@/stores/toast'
import {
  getStudioProject,
  generateVideoClip,
  getVideoTaskStatus,
  cancelVideoTask,
  VIDEO_MODELS,
  EXPORT_RESOLUTIONS,
  EXPORT_FORMATS,
  EXPORT_FPS,
} from '@/api/studio'
import {
  getStoryboardPrompts,
  addShot as apiAddShot,
  updateShot as apiUpdateShot,
  deleteShot as apiDeleteShot,
  type Shot,
  type ShotUpdateRequest,
  SHOT_SIZES,
  CAMERA_ANGLES,
  CAMERA_MOVEMENTS,
  VIDEO_STYLES,
  MOODS,
  LIGHTING_STYLES,
} from '@/api/storyboard'
import { getAssets, type Asset } from '@/api/assets'
import { getMediaUrl } from '@/api/client'
import type { StudioProject, StudioShot, VideoClip, TimelineClip, VideoModel, ExportSettings } from '@/types/studio'
import type { ShotPrompt } from '@/api/storyboard'

const { t, locale } = useI18n()
const route = useRoute()
const toastStore = useToastStore()

// Route params
const novelId = computed(() => route.params.novelId as string)
const chapterId = computed(() => route.params.chapterId as string)

// ============== State ==============

// Loading states
const isLoading = ref(true)
const isSaving = ref(false)
const isGenerating = ref(false)
const error = ref<string | null>(null)

// Project data
const project = ref<StudioProject | null>(null)
const shotPrompts = ref<ShotPrompt[]>([])

// Selection state
const selectedShotSequence = ref<number | null>(null)
const selectedShot = computed<StudioShot | null>(() =>
  project.value?.shots.find(s => s.sequence === selectedShotSequence.value) ?? null
)
const selectedClip = computed<VideoClip | null>(() => {
  if (!selectedShot.value?.selectedClipId) return null
  return selectedShot.value.clips.find(c => c.id === selectedShot.value?.selectedClipId) ?? null
})

// Current shot's prompt
const currentShotPrompt = computed<ShotPrompt | null>(() => {
  if (!selectedShotSequence.value) return null
  return shotPrompts.value.find(p => p.sequence === selectedShotSequence.value) ?? null
})

// Tab state for right panel
const activeTab = ref<'info' | 'camera' | 'subject' | 'environment' | 'style' | 'prompt' | 'generate'>('info')

// Assets for linking
const assets = ref<Asset[]>([])

// Edit state
const isEditing = ref(false)
const editForm = ref<Partial<Shot>>({})

// Shot CRUD modals
const showDeleteConfirm = ref(false)
const deletingShotSequence = ref<number | null>(null)

// Asset selector
const showAssetSelector = ref(false)
const assetSelectorField = ref<'subject' | 'environment'>('subject')
const assetSelectorTypes = ref<string[]>(['person', 'scene', 'item'])

// Video task polling
const pollingIntervals = ref<Map<number, ReturnType<typeof setInterval>>>(new Map())

// Generate settings
const generateSettings = ref<{ model: VideoModel; duration: number }>({
  model: 'vidu',
  duration: 6,
})

// Playback state (UI only, no actual video playback)
const isPlaying = ref(false)
const currentTime = ref(0)

// Timeline state
const videoTrackClips = computed<TimelineClip[]>(() => {
  const track = project.value?.timeline.find(t => t.type === 'video')
  return track?.clips ?? []
})
const timelineTotalDuration = computed(() => {
  const clips = videoTrackClips.value
  if (clips.length === 0) return 0
  const lastClip = clips[clips.length - 1]
  return lastClip.startTime + lastClip.duration
})

// Drag state
const draggingFromGallery = ref<VideoClip | null>(null)
const draggingTimelineIndex = ref<number | null>(null)

// Export modal
const showExportModal = ref(false)
const exportSettings = ref<ExportSettings>({
  format: 'mp4',
  resolution: '1080p',
  fps: 24,
  includeAudio: true,
})

// ============== Data Loading ==============

async function loadData(): Promise<void> {
  if (!chapterId.value) return

  isLoading.value = true
  error.value = null

  try {
    project.value = await getStudioProject(chapterId.value)

    // Load assets for linking
    try {
      const assetsResponse = await getAssets(novelId.value, { page_size: 100 })
      assets.value = assetsResponse.items
    } catch {
      assets.value = []
    }

    try {
      const promptsResponse = await getStoryboardPrompts(chapterId.value, generateSettings.value.model)
      shotPrompts.value = promptsResponse.prompts
    } catch {
      // Prompts are optional, don't fail on error
      shotPrompts.value = []
    }

    // Auto-select first shot
    if (project.value.shots.length > 0 && !selectedShotSequence.value) {
      selectedShotSequence.value = project.value.shots[0].sequence
    }

    // Start polling for any in-progress tasks
    // Note: backend uses 'running'/'queued', frontend uses 'processing'/'pending' - handle both
    for (const shot of project.value.shots) {
      if (shot.video_task_id && shot.video_task_status && ['pending', 'processing', 'running', 'queued'].includes(shot.video_task_status)) {
        startPollingTask(shot.sequence, shot.video_task_id, shot.video_task_platform ?? 'vidu')
      }
    }
  } catch (e: unknown) {
    const message = e instanceof Error ? e.message : 'Failed to load studio data'
    error.value = message
    toastStore.error(message)
  } finally {
    isLoading.value = false
  }
}

onMounted(() => {
  loadData()
})

watch(chapterId, () => {
  loadData()
})

// Re-fetch prompts when model changes (different platforms generate different prompts)
watch(() => generateSettings.value.model, async (newModel) => {
  if (!chapterId.value) return
  try {
    const promptsResponse = await getStoryboardPrompts(chapterId.value, newModel)
    shotPrompts.value = promptsResponse.prompts
  } catch {
    shotPrompts.value = []
  }
})

// ============== Shot Selection ==============

function selectShot(sequence: number): void {
  selectedShotSequence.value = sequence
}

// ============== Video Generation ==============

async function handleGenerateVideo(): Promise<void> {
  if (!selectedShot.value || isGenerating.value) return

  isGenerating.value = true
  const shot = selectedShot.value
  const shotSequence = shot.sequence

  try {
    const prompt = currentShotPrompt.value?.prompt ?? shot.description_cn
    const negativePrompt = currentShotPrompt.value?.negative_prompt ?? null

    const result = await generateVideoClip(
      chapterId.value,
      {
        shotSequence,
        model: generateSettings.value.model,
        duration: generateSettings.value.duration,
      },
      prompt,
      negativePrompt
    )

    // Update shot-level status for tracking (persisted by backend)
    shot.video_task_id = result.taskId
    shot.video_task_platform = generateSettings.value.model
    shot.video_task_status = result.isComplete ? 'success' : 'processing'
    shot.video_task_progress = result.clip.progress
    shot.video_url = result.clip.videoUrl

    // Add clip to gallery
    shot.clips.push(result.clip)

    // Auto-select if it's the first clip
    if (!shot.selectedClipId) {
      shot.selectedClipId = result.clip.id
    }

    if (result.isComplete) {
      toastStore.success(t('studio.clipGenerated'))
    } else {
      // Task didn't complete within 60 seconds, start background polling
      toastStore.info(t('studio.task.processing'))
      startPollingTask(shotSequence, result.taskId, generateSettings.value.model)
    }
  } catch {
    toastStore.error(t('studio.clipGenerateFailed'))
  } finally {
    isGenerating.value = false
  }
}

// ============== Video Task Polling ==============

function startPollingTask(shotSequence: number, taskId: string, platform: string): void {
  // Clear existing interval if any
  stopPollingTask(shotSequence)

  const interval = setInterval(async () => {
    try {
      const status = await getVideoTaskStatus(
        taskId,
        platform,
        chapterId.value,
        shotSequence
      )

      // Update shot status
      const shot = project.value?.shots.find(s => s.sequence === shotSequence)
      if (shot) {
        shot.video_task_status = status.status === 'running' ? 'processing'
          : status.status === 'completed' ? 'success'
          : status.status === 'failed' ? 'failed'
          : 'pending'
        shot.video_task_progress = status.progress
        shot.video_url = status.videoUrl
        shot.video_error = status.error
      }

      // Stop polling if completed or failed
      if (status.status === 'completed' || status.status === 'failed') {
        stopPollingTask(shotSequence)
        if (status.status === 'completed' && status.videoUrl && shot) {
          // Find existing pending/generating clip for this shot and update it
          const existingClip = shot.clips.find(c =>
            c.shotSequence === shotSequence && ['pending', 'generating'].includes(c.status)
          )
          if (existingClip) {
            // Update existing clip
            existingClip.status = 'completed'
            existingClip.progress = 100
            existingClip.videoUrl = status.videoUrl
          } else {
            // No existing clip found, create a new one
            const newClip: VideoClip = {
              id: `clip-${Date.now()}-${shotSequence}`,
              shotSequence,
              model: shot.video_task_platform as VideoModel || 'vidu',
              status: 'completed',
              progress: 100,
              videoUrl: status.videoUrl,
              thumbnailUrl: null,
              duration: generateSettings.value.duration,
              createdAt: new Date().toISOString(),
              prompt: currentShotPrompt.value?.prompt ?? shot.description_cn,
              negativePrompt: currentShotPrompt.value?.negative_prompt ?? null,
              error: null,
            }
            shot.clips.push(newClip)
            // Auto-select the new clip if none selected
            if (!shot.selectedClipId) {
              shot.selectedClipId = newClip.id
            }
          }
          toastStore.success(t('studio.task.succeeded'))
        } else if (status.status === 'failed') {
          // Update existing pending clip to failed status
          const existingClip = shot?.clips.find(c =>
            c.shotSequence === shotSequence && ['pending', 'generating'].includes(c.status)
          )
          if (existingClip) {
            existingClip.status = 'failed'
            existingClip.error = status.error
          }
          toastStore.error(t('studio.task.failed') + (status.error ? `: ${status.error}` : ''))
        }
      }
    } catch (err) {
      console.error('Polling error:', err)
    }
  }, 3000)

  pollingIntervals.value.set(shotSequence, interval)
}

function stopPollingTask(shotSequence: number): void {
  const interval = pollingIntervals.value.get(shotSequence)
  if (interval) {
    clearInterval(interval)
    pollingIntervals.value.delete(shotSequence)
  }
}

async function handleCancelTask(): Promise<void> {
  if (!selectedShot.value) return

  const shot = selectedShot.value
  if (!shot.video_task_id) return

  try {
    await cancelVideoTask(chapterId.value, shot.sequence)
    stopPollingTask(shot.sequence)

    shot.video_task_id = null
    shot.video_task_status = null
    shot.video_task_progress = 0
    shot.video_error = null

    toastStore.success(t('studio.task.cancelled'))
  } catch (err) {
    toastStore.error(t('common.saveFailed'))
  }
}

// ============== Shot CRUD ==============

async function handleAddShot(afterSequence?: number): Promise<void> {
  if (!project.value) return

  isSaving.value = true
  try {
    // 如果没有指定位置，添加到最后
    const insertAfter = afterSequence ?? (
      project.value.shots.length > 0
        ? Math.max(...project.value.shots.map(s => s.sequence))
        : 0
    )

    const newShot = await apiAddShot(chapterId.value, {
      description_cn: t('studio.shot.newShotDescription'),
    }, insertAfter)

    // 重新加载数据以获取正确的排序
    await loadData()

    // Select the new shot
    selectedShotSequence.value = newShot.sequence
    toastStore.success(t('common.saved'))
  } catch (err) {
    toastStore.error(t('common.saveFailed'))
  } finally {
    isSaving.value = false
  }
}

async function handleDeleteShot(): Promise<void> {
  if (deletingShotSequence.value === null || !project.value) return

  isSaving.value = true
  try {
    await apiDeleteShot(chapterId.value, deletingShotSequence.value)

    // Remove from project
    const index = project.value.shots.findIndex(s => s.sequence === deletingShotSequence.value)
    if (index >= 0) {
      project.value.shots.splice(index, 1)
    }

    // Select another shot if the deleted one was selected
    if (selectedShotSequence.value === deletingShotSequence.value) {
      selectedShotSequence.value = project.value.shots[0]?.sequence ?? null
    }

    toastStore.success(t('studio.shot.deleted'))
  } catch (err) {
    toastStore.error(t('common.deleteFailed'))
  } finally {
    isSaving.value = false
    showDeleteConfirm.value = false
    deletingShotSequence.value = null
  }
}

function confirmDeleteShot(sequence: number): void {
  deletingShotSequence.value = sequence
  showDeleteConfirm.value = true
}

function startEditing(): void {
  if (!selectedShot.value) return
  editForm.value = {
    name: selectedShot.value.name,
    description_cn: selectedShot.value.description_cn,
  }
  isEditing.value = true
}

function cancelEditing(): void {
  isEditing.value = false
  editForm.value = {}
}

async function saveEditing(): Promise<void> {
  if (!selectedShot.value) return

  isSaving.value = true
  try {
    const update: ShotUpdateRequest = {}
    if (editForm.value.name !== undefined) update.name = editForm.value.name ?? undefined
    if (editForm.value.description_cn !== undefined) update.description_cn = editForm.value.description_cn

    await apiUpdateShot(chapterId.value, selectedShot.value.sequence, update)

    // Update local state
    if (editForm.value.name !== undefined) selectedShot.value.name = editForm.value.name
    if (editForm.value.description_cn !== undefined) selectedShot.value.description_cn = editForm.value.description_cn

    isEditing.value = false
    editForm.value = {}
    toastStore.success(t('common.saved'))
  } catch (err) {
    toastStore.error(t('common.saveFailed'))
  } finally {
    isSaving.value = false
  }
}

// ============== Clip Selection ==============

function selectClipForShot(clip: VideoClip): void {
  if (!selectedShot.value) return
  selectedShot.value.selectedClipId = clip.id
  toastStore.success(t('studio.clipSelected'))
}

function deleteClipHandler(clip: VideoClip): void {
  if (!selectedShot.value) return
  if (!confirm(t('studio.deleteConfirm'))) return

  const index = selectedShot.value.clips.findIndex(c => c.id === clip.id)
  if (index >= 0) {
    selectedShot.value.clips.splice(index, 1)

    if (selectedShot.value.selectedClipId === clip.id) {
      selectedShot.value.selectedClipId = selectedShot.value.clips[0]?.id ?? null
    }

    toastStore.success(t('studio.clipDeleted'))
  }
}

// ============== Drag and Drop ==============

function handleGalleryDragStart(event: DragEvent, clip: VideoClip): void {
  if (!event.dataTransfer) return
  event.dataTransfer.setData('source', 'gallery')
  event.dataTransfer.setData('clip-id', clip.id)
  event.dataTransfer.setData('shot-sequence', String(clip.shotSequence))
  event.dataTransfer.effectAllowed = 'copy'
  draggingFromGallery.value = clip
}

function handleGalleryDragEnd(): void {
  draggingFromGallery.value = null
}

function handleTimelineDragStart(event: DragEvent, index: number): void {
  if (!event.dataTransfer) return
  event.dataTransfer.setData('source', 'timeline')
  event.dataTransfer.setData('timeline-index', String(index))
  event.dataTransfer.effectAllowed = 'move'
  draggingTimelineIndex.value = index
}

function handleTimelineDragEnd(): void {
  draggingTimelineIndex.value = null
}

function handleTimelineDragOver(event: DragEvent): void {
  event.preventDefault()
  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = 'copy'
  }
}

function handleTimelineDrop(event: DragEvent): void {
  event.preventDefault()
  const data = event.dataTransfer
  if (!data || !project.value) return

  const source = data.getData('source')

  if (source === 'gallery') {
    const clipId = data.getData('clip-id')
    const shotSequence = parseInt(data.getData('shot-sequence'), 10)
    addClipToTimeline(clipId, shotSequence)
  } else if (source === 'timeline') {
    const fromIndex = parseInt(data.getData('timeline-index'), 10)
    const toIndex = videoTrackClips.value.length - 1
    if (fromIndex !== toIndex) {
      reorderTimelineClip(fromIndex, toIndex)
    }
  }

  draggingFromGallery.value = null
  draggingTimelineIndex.value = null
}

function addClipToTimeline(clipId: string, shotSequence: number): void {
  if (!project.value) return

  const shot = project.value.shots.find(s => s.sequence === shotSequence)
  const clip = shot?.clips.find(c => c.id === clipId)
  if (!clip) return

  const videoTrack = project.value.timeline.find(t => t.type === 'video')
  if (!videoTrack) return

  const lastClip = videoTrack.clips[videoTrack.clips.length - 1]
  const startTime = lastClip ? lastClip.startTime + lastClip.duration : 0

  videoTrack.clips.push({
    id: `timeline-${Date.now()}`,
    clipId: clip.id,
    shotSequence: clip.shotSequence,
    startTime,
    duration: clip.duration,
    thumbnailUrl: clip.thumbnailUrl,
  })

  toastStore.success(t('studio.savedToTimeline'))
}

function reorderTimelineClip(fromIndex: number, toIndex: number): void {
  if (!project.value) return

  const videoTrack = project.value.timeline.find(t => t.type === 'video')
  if (!videoTrack) return

  const [clip] = videoTrack.clips.splice(fromIndex, 1)
  videoTrack.clips.splice(toIndex, 0, clip)

  // Recalculate start times
  let time = 0
  for (const c of videoTrack.clips) {
    c.startTime = time
    time += c.duration
  }
}

function removeFromTimeline(index: number): void {
  if (!project.value) return

  const videoTrack = project.value.timeline.find(t => t.type === 'video')
  if (!videoTrack) return

  videoTrack.clips.splice(index, 1)

  let time = 0
  for (const c of videoTrack.clips) {
    c.startTime = time
    time += c.duration
  }
}

function clearTimeline(): void {
  if (!project.value) return
  const videoTrack = project.value.timeline.find(t => t.type === 'video')
  if (videoTrack) {
    videoTrack.clips = []
  }
}

function autoArrangeTimeline(): void {
  if (!project.value) return

  const videoTrack = project.value.timeline.find(t => t.type === 'video')
  if (!videoTrack) return

  videoTrack.clips = []

  let time = 0
  for (const shot of project.value.shots) {
    if (shot.selectedClipId) {
      const clip = shot.clips.find(c => c.id === shot.selectedClipId)
      if (clip) {
        videoTrack.clips.push({
          id: `timeline-${Date.now()}-${shot.sequence}`,
          clipId: clip.id,
          shotSequence: shot.sequence,
          startTime: time,
          duration: clip.duration,
          thumbnailUrl: clip.thumbnailUrl,
        })
        time += clip.duration
      }
    }
  }

  toastStore.success(t('studio.savedToTimeline'))
}

// ============== Playback (UI only) ==============

function togglePlay(): void {
  isPlaying.value = !isPlaying.value
}

let playbackInterval: number | null = null

watch(isPlaying, (playing) => {
  if (playing) {
    playbackInterval = window.setInterval(() => {
      if (currentTime.value < timelineTotalDuration.value) {
        currentTime.value += 0.1
      } else {
        isPlaying.value = false
        currentTime.value = 0
      }
    }, 100)
  } else if (playbackInterval) {
    window.clearInterval(playbackInterval)
    playbackInterval = null
  }
})

onUnmounted(() => {
  if (playbackInterval) {
    window.clearInterval(playbackInterval)
  }
  // Clean up all polling intervals
  for (const interval of pollingIntervals.value.values()) {
    clearInterval(interval)
  }
  pollingIntervals.value.clear()
})

// ============== Compose & Export ==============

function handleCompose(): void {
  const shotsWithoutClips = project.value?.shots.filter(s => !s.selectedClipId) ?? []
  if (shotsWithoutClips.length > 0) {
    toastStore.warning(t('studio.compose.missingClips', { count: shotsWithoutClips.length }))
    return
  }
  showExportModal.value = true
}

function handleExport(): void {
  toastStore.success(t('studio.compose.complete'))
  showExportModal.value = false
}

// ============== Asset Helpers ==============

function getAssetById(id: string): Asset | undefined {
  return assets.value.find(a => a.id === id)
}

function getAssetName(id: string): string {
  const asset = getAssetById(id)
  return asset?.canonical_name || id
}

function openAssetSelector(field: 'subject' | 'environment', types: string[]): void {
  assetSelectorField.value = field
  assetSelectorTypes.value = types
  showAssetSelector.value = true
}

function selectAsset(asset: Asset): void {
  if (!selectedShot.value) return

  if (assetSelectorField.value === 'subject') {
    if (!selectedShot.value.subject) {
      (selectedShot.value as any).subject = { asset_refs: [] }
    }
    if (!selectedShot.value.subject.asset_refs) {
      selectedShot.value.subject.asset_refs = []
    }
    if (!selectedShot.value.subject.asset_refs.includes(asset.id)) {
      selectedShot.value.subject.asset_refs.push(asset.id)
      handleSaveField('subject', { asset_refs: selectedShot.value.subject.asset_refs })
    }
    // Auto-fill description if empty
    if (!selectedShot.value.subject.subject_description && asset.base_traits) {
      selectedShot.value.subject.subject_description = asset.base_traits
      handleSaveField('subject', { subject_description: asset.base_traits })
    }
  } else if (assetSelectorField.value === 'environment') {
    if (!selectedShot.value.environment) {
      (selectedShot.value as any).environment = {}
    }
    selectedShot.value.environment.scene_asset_ref = asset.id
    handleSaveField('environment', { scene_asset_ref: asset.id })
    // Auto-fill location if empty
    if (!selectedShot.value.environment.location && asset.base_traits) {
      selectedShot.value.environment.location = asset.base_traits
      handleSaveField('environment', { location: asset.base_traits })
    }
  }

  showAssetSelector.value = false
}

function removeAssetRef(id: string): void {
  if (!selectedShot.value?.subject?.asset_refs) return
  selectedShot.value.subject.asset_refs = selectedShot.value.subject.asset_refs.filter(ref => ref !== id)
  handleSaveField('subject', { asset_refs: selectedShot.value.subject.asset_refs })
}

// ============== Field Save (Auto-save on change) ==============

async function handleSaveField(
  section: 'camera' | 'subject' | 'environment' | 'style' | 'audio' | 'technical',
  updates: Record<string, any>
): Promise<void> {
  if (!selectedShot.value) return

  try {
    const updatePayload: ShotUpdateRequest = {
      [section]: updates,
    }
    await apiUpdateShot(chapterId.value, selectedShot.value.sequence, updatePayload)
  } catch {
    toastStore.error(t('common.saveFailed'))
  }
}

// ============== Helpers ==============

function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  const ms = Math.floor((seconds % 1) * 10)
  return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}.${ms}`
}

function copyPrompt(text: string): void {
  navigator.clipboard.writeText(text)
  toastStore.success(t('studio.promptCopied'))
}

function getModelLabel(value: VideoModel): string {
  const model = VIDEO_MODELS.find(m => m.value === value)
  return locale.value === 'zh-CN' ? (model?.labelZh ?? value) : (model?.label ?? value)
}
</script>

<template>
  <div class="studio-view h-full flex flex-col bg-gray-100 dark:bg-gray-900">
    <!-- Loading State -->
    <div v-if="isLoading" class="flex-1 flex items-center justify-center">
      <div class="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-primary-500" />
    </div>

    <!-- Error State -->
    <div v-else-if="error" class="flex-1 flex items-center justify-center">
      <div class="text-center">
        <p class="text-red-500 mb-4">{{ error }}</p>
        <button class="btn-primary" @click="loadData">Retry</button>
      </div>
    </div>

    <!-- Main Content -->
    <template v-else-if="project">
      <!-- Toolbar -->
      <div class="flex-none h-14 px-4 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
        <!-- Left: Playback controls -->
        <div class="flex items-center gap-4">
          <button
            class="w-10 h-10 rounded-full bg-primary-500 hover:bg-primary-600 text-white flex items-center justify-center transition-colors"
            @click="togglePlay"
          >
            <svg v-if="!isPlaying" class="w-5 h-5 ml-0.5" fill="currentColor" viewBox="0 0 24 24">
              <path d="M8 5v14l11-7z" />
            </svg>
            <svg v-else class="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
              <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z" />
            </svg>
          </button>
          <span class="text-sm font-mono text-gray-600 dark:text-gray-400">
            {{ formatTime(currentTime) }} / {{ formatTime(timelineTotalDuration) }}
          </span>
        </div>

        <!-- Right: Actions -->
        <div class="flex items-center gap-2">
          <button class="btn-secondary" @click="showExportModal = true">
            {{ t('studio.exportSettings') }}
          </button>
          <button class="btn-primary" @click="handleCompose">
            {{ t('studio.composeVideo') }}
          </button>
        </div>
      </div>

      <!-- Main Content Area -->
      <div class="flex-1 flex overflow-hidden">
        <!-- Left Panel - Shot List -->
        <div class="w-72 flex-none border-r border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 flex flex-col">
          <div class="flex-none p-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
            <h3 class="font-semibold text-gray-900 dark:text-white">{{ t('studio.shotList') }}</h3>
            <button
              class="w-8 h-8 rounded-lg bg-primary-500 hover:bg-primary-600 text-white flex items-center justify-center transition-colors"
              :disabled="isSaving"
              @click="handleAddShot()"
              :title="t('studio.shot.add')"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
              </svg>
            </button>
          </div>

          <div class="flex-1 overflow-y-auto p-2">
            <div v-if="project.shots.length === 0" class="text-center py-8 text-gray-500">
              <p>{{ t('studio.noShots') }}</p>
              <p class="text-sm mt-2">{{ t('studio.noShotsHint') }}</p>
            </div>

            <div
              v-for="shot in project.shots"
              :key="shot.sequence"
              :class="[
                'p-3 rounded-lg cursor-pointer transition-all mb-2 group',
                selectedShotSequence === shot.sequence
                  ? 'bg-primary-100 dark:bg-primary-900/30 border-2 border-primary-500'
                  : 'bg-gray-50 dark:bg-gray-700/50 hover:bg-gray-100 dark:hover:bg-gray-700 border-2 border-transparent',
              ]"
              @click="selectShot(shot.sequence)"
            >
              <div class="flex items-start gap-3">
                <span
                  :class="[
                    'w-7 h-7 rounded-full flex items-center justify-center text-xs font-medium flex-shrink-0',
                    shot.selectedClipId
                      ? 'bg-green-500 text-white'
                      : shot.clips.length > 0
                        ? 'bg-yellow-500 text-white'
                        : 'bg-gray-300 dark:bg-gray-600 text-gray-700 dark:text-gray-300',
                  ]"
                >
                  {{ shot.selectedClipId ? '✓' : shot.sequence }}
                </span>
                <div class="flex-1 min-w-0">
                  <p class="font-medium text-gray-900 dark:text-white truncate">
                    {{ shot.name || t('studio.shotNumber', { number: shot.sequence }) }}
                  </p>
                  <p class="text-xs text-gray-500 dark:text-gray-400 truncate mt-0.5">
                    {{ shot.description_cn }}
                  </p>
                  <div class="flex items-center gap-2 mt-1">
                    <!-- Clip count badge -->
                    <span
                      :class="[
                        'px-1.5 py-0.5 rounded text-xs',
                        shot.clips.length > 0
                          ? 'bg-primary-100 dark:bg-primary-900/50 text-primary-700 dark:text-primary-300'
                          : 'bg-gray-200 dark:bg-gray-600 text-gray-600 dark:text-gray-400',
                      ]"
                    >
                      {{ shot.clips.length > 0 ? t('studio.clipsCount', { count: shot.clips.length }) : t('studio.noClip') }}
                    </span>
                    <!-- Video task status -->
                    <span
                      v-if="['pending', 'processing', 'running', 'queued'].includes(shot.video_task_status || '')"
                      class="px-1.5 py-0.5 rounded text-xs bg-blue-100 dark:bg-blue-900/50 text-blue-700 dark:text-blue-300 flex items-center gap-1"
                    >
                      <span class="animate-spin w-3 h-3 border-2 border-blue-500 border-t-transparent rounded-full" />
                      {{ Math.round(shot.video_task_progress || 0) }}%
                    </span>
                    <span
                      v-else-if="['success', 'completed', 'succeeded'].includes(shot.video_task_status || '')"
                      class="px-1.5 py-0.5 rounded text-xs bg-green-100 dark:bg-green-900/50 text-green-700 dark:text-green-300"
                    >
                      ✓
                    </span>
                    <span
                      v-else-if="shot.video_task_status === 'failed'"
                      class="px-1.5 py-0.5 rounded text-xs bg-red-100 dark:bg-red-900/50 text-red-700 dark:text-red-300"
                    >
                      ✗
                    </span>
                  </div>
                </div>
                <!-- Delete button -->
                <button
                  class="flex-shrink-0 w-6 h-6 rounded text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                  @click.stop="confirmDeleteShot(shot.sequence)"
                  :title="t('studio.shot.delete')"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </button>
              </div>
              <!-- Insert after this shot button -->
              <button
                class="w-full h-6 flex items-center justify-center text-gray-400 hover:text-primary-500 hover:bg-primary-50 dark:hover:bg-primary-900/20 -mt-1 mb-1 rounded opacity-0 group-hover:opacity-100 transition-opacity"
                @click.stop="handleAddShot(shot.sequence)"
                :title="t('studio.shot.addAfter')"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
                </svg>
              </button>
            </div>
          </div>
        </div>

        <!-- Center Area - Preview + Gallery -->
        <div class="flex-1 flex flex-col overflow-hidden">
          <!-- Video Preview -->
          <div class="flex-none p-4">
            <div class="bg-black rounded-lg overflow-hidden aspect-video flex items-center justify-center">
              <div v-if="!selectedClip" class="text-gray-500">
                {{ t('studio.noPreview') }}
              </div>
              <div v-else class="text-white text-center">
                <p class="text-lg font-medium">{{ t('studio.shotNumber', { number: selectedClip.shotSequence }) }}</p>
                <p class="text-sm text-gray-400 mt-1">{{ getModelLabel(selectedClip.model) }} · {{ selectedClip.duration }}s</p>
              </div>
            </div>
          </div>

          <!-- Video Gallery -->
          <div class="flex-1 overflow-hidden flex flex-col border-t border-gray-200 dark:border-gray-700">
            <div class="flex-none px-4 py-2 bg-gray-50 dark:bg-gray-800 flex items-center justify-between">
              <h4 class="text-sm font-medium text-gray-700 dark:text-gray-300">{{ t('studio.videoGallery') }}</h4>
              <span class="text-xs text-gray-500">{{ t('studio.dragToTimeline') }}</span>
            </div>
            <div class="flex-1 overflow-y-auto p-4">
              <div v-if="!selectedShot" class="text-center py-8 text-gray-500">
                {{ t('studio.noPreview') }}
              </div>
              <div v-else-if="selectedShot.clips.length === 0" class="text-center py-8 text-gray-500">
                <p>{{ t('studio.galleryEmpty') }}</p>
                <p class="text-sm mt-2">{{ t('studio.galleryHint') }}</p>
              </div>
              <div v-else class="grid grid-cols-3 gap-3">
                <div
                  v-for="clip in selectedShot.clips"
                  :key="clip.id"
                  :class="[
                    'relative aspect-video rounded-lg overflow-hidden cursor-move border-2 transition-all group',
                    selectedShot.selectedClipId === clip.id
                      ? 'border-primary-500 ring-2 ring-primary-500/30'
                      : 'border-gray-300 dark:border-gray-600 hover:border-gray-400',
                  ]"
                  draggable="true"
                  @dragstart="handleGalleryDragStart($event, clip)"
                  @dragend="handleGalleryDragEnd"
                >
                  <!-- Video Preview or Placeholder -->
                  <div class="absolute inset-0 bg-gray-800 flex items-center justify-center">
                    <video
                      v-if="clip.videoUrl"
                      :src="clip.videoUrl"
                      class="w-full h-full object-cover"
                      muted
                      loop
                      @mouseenter="($event.target as HTMLVideoElement).play()"
                      @mouseleave="($event.target as HTMLVideoElement).pause()"
                    />
                    <div v-else class="text-center text-gray-400">
                      <p class="text-xs">{{ getModelLabel(clip.model) }}</p>
                      <p class="text-lg font-bold">{{ clip.duration }}s</p>
                    </div>
                  </div>

                  <!-- Selected badge -->
                  <div v-if="selectedShot.selectedClipId === clip.id" class="absolute top-1 left-1">
                    <span class="px-1.5 py-0.5 bg-primary-500 text-white text-xs rounded font-medium">
                      {{ t('studio.selectedVideo') }}
                    </span>
                  </div>

                  <!-- Hover overlay -->
                  <div class="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-2">
                    <button
                      class="px-2 py-1 bg-primary-500 hover:bg-primary-600 text-white text-xs rounded transition-colors"
                      @click.stop="selectClipForShot(clip)"
                    >
                      {{ t('studio.selectVideo') }}
                    </button>
                    <button
                      class="px-2 py-1 bg-red-500 hover:bg-red-600 text-white text-xs rounded transition-colors"
                      @click.stop="deleteClipHandler(clip)"
                    >
                      {{ t('studio.deleteVideo') }}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Right Panel - Tabbed Properties -->
        <div class="w-1/5 flex-none border-l border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 flex flex-col overflow-hidden">
          <div v-if="!selectedShot" class="flex-1 flex items-center justify-center text-gray-500">
            {{ t('studio.noPreview') }}
          </div>
          <template v-else>
            <!-- Tab Header -->
            <div class="flex-none border-b border-gray-200 dark:border-gray-700">
              <div class="flex overflow-x-auto">
                <button
                  v-for="tab in [
                    { key: 'info', label: t('studio.tabs.info') },
                    { key: 'camera', label: t('studio.tabs.camera') },
                    { key: 'subject', label: t('studio.tabs.subject') },
                    { key: 'environment', label: t('studio.tabs.environment') },
                    { key: 'style', label: t('studio.tabs.style') },
                    { key: 'prompt', label: t('studio.tabs.prompt') },
                    { key: 'generate', label: t('studio.tabs.generate') },
                  ]"
                  :key="tab.key"
                  :class="[
                    'flex-1 px-3 py-2.5 text-xs font-medium transition-colors',
                    activeTab === tab.key
                      ? 'text-primary-600 dark:text-primary-400 border-b-2 border-primary-500'
                      : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300',
                  ]"
                  @click="activeTab = tab.key as typeof activeTab"
                >
                  {{ tab.label }}
                </button>
              </div>
            </div>

            <!-- Tab: Shot Info -->
            <div v-if="activeTab === 'info'" class="flex-1 overflow-y-auto p-4 space-y-4">
              <template v-if="!isEditing">
                <div>
                  <h4 class="text-xs font-medium text-gray-500 mb-1">{{ t('studio.shotNumber', { number: selectedShot.sequence }) }}</h4>
                  <p class="font-medium text-gray-900 dark:text-white">
                    {{ selectedShot.name || t('studio.shotNumber', { number: selectedShot.sequence }) }}
                  </p>
                </div>
                <div>
                  <h4 class="text-xs font-medium text-gray-500 mb-1">{{ t('studio.description') }}</h4>
                  <p class="text-sm text-gray-700 dark:text-gray-300">
                    {{ selectedShot.description_cn }}
                  </p>
                </div>
                <button class="btn-secondary w-full" @click="startEditing">
                  {{ t('studio.shot.edit') }}
                </button>
              </template>
              <template v-else>
                <div>
                  <label class="label">{{ t('storyboard.editModal.name') }}</label>
                  <input v-model="editForm.name" type="text" class="input w-full" />
                </div>
                <div>
                  <label class="label">{{ t('studio.description') }}</label>
                  <textarea
                    v-model="editForm.description_cn"
                    rows="4"
                    class="input w-full resize-none"
                  />
                </div>
                <div class="flex gap-2">
                  <button class="btn-secondary flex-1" @click="cancelEditing">
                    {{ t('studio.shot.cancel') }}
                  </button>
                  <button class="btn-primary flex-1" :disabled="isSaving" @click="saveEditing">
                    {{ t('studio.shot.save') }}
                  </button>
                </div>
              </template>
            </div>

            <!-- Tab: Camera Settings -->
            <div v-else-if="activeTab === 'camera'" class="flex-1 overflow-y-auto p-4 space-y-4">
              <div>
                <label class="label">{{ t('storyboard.camera.shotSize') }}</label>
                <select
                  :value="selectedShot.camera?.shot_size"
                  class="input w-full"
                  @change="(e: Event) => {
                    const value = (e.target as HTMLSelectElement).value
                    if (selectedShot) {
                      if (!selectedShot.camera) (selectedShot as any).camera = {}
                      selectedShot.camera.shot_size = value
                      handleSaveField('camera', { shot_size: value })
                    }
                  }"
                >
                  <option v-for="s in SHOT_SIZES" :key="s.value" :value="s.value">
                    {{ s.label }} ({{ s.labelEn }})
                  </option>
                </select>
              </div>

              <div>
                <label class="label">{{ t('storyboard.camera.cameraAngle') }}</label>
                <select
                  :value="selectedShot.camera?.camera_angle"
                  class="input w-full"
                  @change="(e: Event) => {
                    const value = (e.target as HTMLSelectElement).value
                    if (selectedShot) {
                      if (!selectedShot.camera) (selectedShot as any).camera = {}
                      selectedShot.camera.camera_angle = value
                      handleSaveField('camera', { camera_angle: value })
                    }
                  }"
                >
                  <option v-for="a in CAMERA_ANGLES" :key="a.value" :value="a.value">
                    {{ a.label }} ({{ a.labelEn }})
                  </option>
                </select>
              </div>

              <div>
                <label class="label">{{ t('storyboard.camera.cameraMovement') }}</label>
                <select
                  :value="selectedShot.camera?.camera_movement"
                  class="input w-full"
                  @change="(e: Event) => {
                    const value = (e.target as HTMLSelectElement).value
                    if (selectedShot) {
                      if (!selectedShot.camera) (selectedShot as any).camera = {}
                      selectedShot.camera.camera_movement = value
                      handleSaveField('camera', { camera_movement: value })
                    }
                  }"
                >
                  <option v-for="m in CAMERA_MOVEMENTS" :key="m.value" :value="m.value">
                    {{ m.label }} ({{ m.labelEn }})
                  </option>
                </select>
              </div>
            </div>

            <!-- Tab: Subject & Action -->
            <div v-else-if="activeTab === 'subject'" class="flex-1 overflow-y-auto p-4 space-y-4">
              <div>
                <label class="label">{{ t('storyboard.subject.linkedAssets') }}</label>
                <div class="flex flex-wrap gap-2 mb-2">
                  <span
                    v-for="assetId in selectedShot.subject?.asset_refs || []"
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
                    <button type="button" class="hover:text-red-500" @click="removeAssetRef(assetId)">×</button>
                  </span>
                </div>
                <button
                  type="button"
                  class="btn-secondary btn-sm w-full"
                  @click="openAssetSelector('subject', ['person', 'item'])"
                >
                  {{ t('storyboard.edit.addCharacterOrItem') }}
                </button>
              </div>

              <div>
                <label class="label">{{ t('storyboard.subject.subjectDescription') }}</label>
                <textarea
                  :value="selectedShot.subject?.subject_description"
                  rows="3"
                  class="input w-full resize-none"
                  placeholder="e.g., A young woman with long black hair wearing a red dress"
                  @blur="(e: Event) => {
                    const value = (e.target as HTMLTextAreaElement).value
                    if (selectedShot) {
                      if (!selectedShot.subject) (selectedShot as any).subject = {}
                      selectedShot.subject.subject_description = value
                      handleSaveField('subject', { subject_description: value })
                    }
                  }"
                />
              </div>

              <div>
                <label class="label">{{ t('storyboard.subject.action') }}</label>
                <input
                  :value="selectedShot.subject?.action"
                  type="text"
                  class="input w-full"
                  placeholder="e.g., walking slowly towards the window"
                  @blur="(e: Event) => {
                    const value = (e.target as HTMLInputElement).value
                    if (selectedShot) {
                      if (!selectedShot.subject) (selectedShot as any).subject = {}
                      selectedShot.subject.action = value
                      handleSaveField('subject', { action: value })
                    }
                  }"
                />
              </div>

              <div>
                <label class="label">{{ t('storyboard.subject.emotion') }}</label>
                <input
                  :value="selectedShot.subject?.emotion"
                  type="text"
                  class="input w-full"
                  placeholder="e.g., subtle sadness, thoughtful expression"
                  @blur="(e: Event) => {
                    const value = (e.target as HTMLInputElement).value
                    if (selectedShot) {
                      if (!selectedShot.subject) (selectedShot as any).subject = {}
                      selectedShot.subject.emotion = value
                      handleSaveField('subject', { emotion: value })
                    }
                  }"
                />
              </div>
            </div>

            <!-- Tab: Environment Settings -->
            <div v-else-if="activeTab === 'environment'" class="flex-1 overflow-y-auto p-4 space-y-4">
              <div>
                <label class="label">{{ t('storyboard.edit.sceneAsset') }}</label>
                <div class="flex items-center gap-2 mb-2">
                  <span v-if="selectedShot.environment?.scene_asset_ref" class="px-2 py-1 rounded bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 text-sm flex items-center gap-1">
                    <img
                      v-if="getAssetById(selectedShot.environment.scene_asset_ref)?.main_image"
                      :src="getMediaUrl(getAssetById(selectedShot.environment.scene_asset_ref)?.main_image)"
                      class="w-4 h-4 rounded object-cover"
                      alt=""
                    />
                    {{ getAssetName(selectedShot.environment.scene_asset_ref) }}
                  </span>
                </div>
                <button
                  type="button"
                  class="btn-secondary btn-sm w-full"
                  @click="openAssetSelector('environment', ['scene'])"
                >
                  {{ selectedShot.environment?.scene_asset_ref ? t('storyboard.edit.change') : t('storyboard.edit.selectScene') }}
                </button>
              </div>

              <div>
                <label class="label">{{ t('storyboard.environment.location') }}</label>
                <textarea
                  :value="selectedShot.environment?.location"
                  rows="3"
                  class="input w-full resize-none"
                  placeholder="e.g., A cozy living room with vintage furniture and warm lighting"
                  @blur="(e: Event) => {
                    const value = (e.target as HTMLTextAreaElement).value
                    if (selectedShot) {
                      if (!selectedShot.environment) (selectedShot as any).environment = {}
                      selectedShot.environment.location = value
                      handleSaveField('environment', { location: value })
                    }
                  }"
                />
              </div>

              <div>
                <label class="label">{{ t('storyboard.environment.timeOfDay') }}</label>
                <select
                  :value="selectedShot.environment?.time_of_day"
                  class="input w-full"
                  @change="(e: Event) => {
                    const value = (e.target as HTMLSelectElement).value
                    if (selectedShot) {
                      if (!selectedShot.environment) (selectedShot as any).environment = {}
                      selectedShot.environment.time_of_day = value
                      handleSaveField('environment', { time_of_day: value })
                    }
                  }"
                >
                  <option value="dawn">{{ t('storyboard.timeOfDays.dawn') }}</option>
                  <option value="morning">{{ t('storyboard.timeOfDays.morning') }}</option>
                  <option value="noon">{{ t('storyboard.timeOfDays.noon') }}</option>
                  <option value="afternoon">{{ t('storyboard.timeOfDays.afternoon') }}</option>
                  <option value="dusk">{{ t('storyboard.timeOfDays.dusk') }}</option>
                  <option value="night">{{ t('storyboard.timeOfDays.night') }}</option>
                </select>
              </div>

              <div>
                <label class="label">{{ t('storyboard.environment.lighting') }}</label>
                <select
                  :value="selectedShot.environment?.lighting"
                  class="input w-full"
                  @change="(e: Event) => {
                    const value = (e.target as HTMLSelectElement).value
                    if (selectedShot) {
                      if (!selectedShot.environment) (selectedShot as any).environment = {}
                      selectedShot.environment.lighting = value
                      handleSaveField('environment', { lighting: value })
                    }
                  }"
                >
                  <option v-for="l in LIGHTING_STYLES" :key="l.value" :value="l.value">
                    {{ l.label }}
                  </option>
                </select>
              </div>
            </div>

            <!-- Tab: Style Settings -->
            <div v-else-if="activeTab === 'style'" class="flex-1 overflow-y-auto p-4 space-y-4">
              <div>
                <label class="label">{{ t('storyboard.style.videoStyle') }}</label>
                <select
                  :value="selectedShot.style?.video_style"
                  class="input w-full"
                  @change="(e: Event) => {
                    const value = (e.target as HTMLSelectElement).value
                    if (selectedShot) {
                      if (!selectedShot.style) (selectedShot as any).style = {}
                      selectedShot.style.video_style = value
                      handleSaveField('style', { video_style: value })
                    }
                  }"
                >
                  <option v-for="s in VIDEO_STYLES" :key="s.value" :value="s.value">
                    {{ s.label }}
                  </option>
                </select>
              </div>

              <div>
                <label class="label">{{ t('storyboard.style.mood') }}</label>
                <select
                  :value="selectedShot.style?.mood"
                  class="input w-full"
                  @change="(e: Event) => {
                    const value = (e.target as HTMLSelectElement).value
                    if (selectedShot) {
                      if (!selectedShot.style) (selectedShot as any).style = {}
                      selectedShot.style.mood = value
                      handleSaveField('style', { mood: value })
                    }
                  }"
                >
                  <option v-for="m in MOODS" :key="m.value" :value="m.value">
                    {{ m.label }}
                  </option>
                </select>
              </div>

              <div>
                <label class="label">{{ t('storyboard.style.colorGrading') }}</label>
                <input
                  :value="selectedShot.style?.color_grading"
                  type="text"
                  class="input w-full"
                  placeholder="e.g., teal-orange, warm, desaturated"
                  @blur="(e: Event) => {
                    const value = (e.target as HTMLInputElement).value
                    if (selectedShot) {
                      if (!selectedShot.style) (selectedShot as any).style = {}
                      selectedShot.style.color_grading = value
                      handleSaveField('style', { color_grading: value })
                    }
                  }"
                />
              </div>
            </div>

            <!-- Tab: Prompt Preview -->
            <div v-else-if="activeTab === 'prompt'" class="flex-1 overflow-y-auto p-4">
              <div v-if="currentShotPrompt" class="space-y-4">
                <div>
                  <div class="flex items-center justify-between mb-1">
                    <span class="text-xs font-medium text-gray-500">{{ t('studio.prompt') }}</span>
                    <button
                      class="text-xs text-primary-500 hover:text-primary-600"
                      @click="copyPrompt(currentShotPrompt.prompt)"
                    >
                      {{ t('studio.copyPrompt') }}
                    </button>
                  </div>
                  <p class="text-xs text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-700 rounded p-2 whitespace-pre-wrap">
                    {{ currentShotPrompt.prompt }}
                  </p>
                </div>

                <div v-if="currentShotPrompt.negative_prompt">
                  <div class="flex items-center justify-between mb-1">
                    <span class="text-xs font-medium text-gray-500">{{ t('studio.negativePrompt') }}</span>
                    <button
                      class="text-xs text-primary-500 hover:text-primary-600"
                      @click="copyPrompt(currentShotPrompt.negative_prompt)"
                    >
                      {{ t('studio.copyPrompt') }}
                    </button>
                  </div>
                  <p class="text-xs text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-700 rounded p-2 whitespace-pre-wrap">
                    {{ currentShotPrompt.negative_prompt }}
                  </p>
                </div>
              </div>
              <div v-else class="text-sm text-gray-500 text-center py-8">
                {{ t('studio.noPreview') }}
              </div>
            </div>

            <!-- Tab: Generate Video -->
            <div v-else-if="activeTab === 'generate'" class="flex-1 overflow-y-auto p-4 space-y-4">
              <!-- Video task progress -->
              <div v-if="selectedShot.video_task_status === 'pending' || selectedShot.video_task_status === 'processing' || selectedShot.video_task_status === 'running' || selectedShot.video_task_status === 'queued'" class="p-3 rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800">
                <div class="flex items-center justify-between mb-2">
                  <span class="text-sm font-medium text-blue-700 dark:text-blue-300">{{ t('studio.task.progress') }}</span>
                  <span class="text-sm text-blue-600 dark:text-blue-400">{{ Math.round(selectedShot.video_task_progress || 0) }}%</span>
                </div>
                <div class="h-2 bg-blue-200 dark:bg-blue-800 rounded-full overflow-hidden">
                  <div
                    class="h-full bg-blue-500 transition-all duration-300"
                    :style="{ width: `${selectedShot.video_task_progress || 0}%` }"
                  />
                </div>
                <button
                  class="mt-3 text-sm text-red-500 hover:text-red-600 w-full text-center"
                  @click="handleCancelTask"
                >
                  {{ t('studio.task.cancel') }}
                </button>
              </div>

              <!-- Success state -->
              <div v-else-if="['success', 'completed', 'succeeded'].includes(selectedShot.video_task_status || '') && selectedShot.video_url" class="p-3 rounded-lg bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800">
                <p class="text-sm font-medium text-green-700 dark:text-green-300 mb-2">{{ t('studio.task.succeeded') }}</p>
                <video
                  :src="selectedShot.video_url"
                  controls
                  class="w-full rounded"
                />
              </div>

              <!-- Failed state -->
              <div v-else-if="selectedShot.video_task_status === 'failed'" class="p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
                <p class="text-sm font-medium text-red-700 dark:text-red-300">{{ t('studio.task.failed') }}</p>
                <p v-if="selectedShot.video_error" class="text-xs text-red-600 dark:text-red-400 mt-1">
                  {{ selectedShot.video_error }}
                </p>
                <button
                  class="mt-3 btn-primary w-full"
                  @click="handleCancelTask"
                >
                  {{ t('studio.task.retry') }}
                </button>
              </div>

              <!-- Generate settings (always show unless actively generating) -->
              <template v-if="!['pending', 'processing', 'running', 'queued'].includes(selectedShot.video_task_status || '')">
                <div>
                  <label class="label">{{ t('studio.model') }}</label>
                  <select v-model="generateSettings.model" class="input w-full">
                    <option
                      v-for="m in VIDEO_MODELS"
                      :key="m.value"
                      :value="m.value"
                      :disabled="m.disabled"
                    >
                      {{ locale === 'zh-CN' ? m.labelZh : m.label }}{{ m.disabled ? ` (${t('studio.unavailable')})` : '' }}
                    </option>
                  </select>
                  <p v-if="generateSettings.model" class="text-xs text-gray-500 mt-1">
                    {{ locale === 'zh-CN' ? VIDEO_MODELS.find(m => m.value === generateSettings.model)?.descriptionZh : VIDEO_MODELS.find(m => m.value === generateSettings.model)?.description }}
                  </p>
                </div>

                <div>
                  <label class="label">
                    {{ t('studio.duration') }}: {{ t('studio.durationSeconds', { seconds: generateSettings.duration }) }}
                  </label>
                  <input
                    v-model.number="generateSettings.duration"
                    type="range"
                    min="2"
                    max="10"
                    step="1"
                    class="w-full"
                  />
                </div>

                <button
                  class="btn-primary w-full"
                  :disabled="isGenerating || ['processing', 'running', 'queued', 'pending'].includes(selectedShot.video_task_status || '')"
                  @click="handleGenerateVideo"
                >
                  <span v-if="isGenerating" class="flex items-center justify-center gap-2">
                    <span class="animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent" />
                    {{ t('studio.generating') }}
                  </span>
                  <span v-else>
                    {{ selectedShot.video_url ? t('studio.regenerate') : t('studio.generate') }}
                  </span>
                </button>
              </template>
            </div>

            </template>
        </div>
      </div>

      <!-- Timeline -->
      <div class="flex-none h-48 border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 flex flex-col">
        <!-- Timeline Header -->
        <div class="flex-none h-10 px-4 flex items-center justify-between border-b border-gray-200 dark:border-gray-700">
          <h4 class="text-sm font-medium text-gray-700 dark:text-gray-300">{{ t('studio.timeline') }}</h4>
          <div class="flex items-center gap-2">
            <button class="text-xs text-primary-500 hover:text-primary-600" @click="autoArrangeTimeline">
              {{ t('studio.autoArrange') }}
            </button>
            <button class="text-xs text-red-500 hover:text-red-600" @click="clearTimeline">
              {{ t('studio.clearTimeline') }}
            </button>
          </div>
        </div>

        <!-- Time Ruler -->
        <div class="flex-none h-6 flex items-center px-4 bg-gray-50 dark:bg-gray-700/50 border-b border-gray-200 dark:border-gray-700">
          <div class="w-20 flex-shrink-0" />
          <div class="flex-1 flex">
            <template v-for="i in Math.max(Math.ceil(timelineTotalDuration / 5) + 1, 6)" :key="i">
              <span class="text-xs text-gray-400 w-24">{{ formatTime((i - 1) * 5) }}</span>
            </template>
          </div>
        </div>

        <!-- Video Track -->
        <div
          class="flex-1 flex items-center px-4 gap-1 overflow-x-auto"
          @dragover="handleTimelineDragOver"
          @drop="handleTimelineDrop"
        >
          <div class="w-20 flex-shrink-0 text-xs text-gray-500 dark:text-gray-400">
            {{ t('studio.videoTrack') }}
          </div>
          <div class="flex-1 flex items-center gap-1 h-16">
            <div
              v-for="(clip, index) in videoTrackClips"
              :key="clip.id"
              :style="{ width: `${Math.max(clip.duration * 20, 60)}px` }"
              class="h-full rounded bg-primary-500/80 hover:bg-primary-600/80 flex-shrink-0 cursor-move relative group transition-colors"
              draggable="true"
              @dragstart="handleTimelineDragStart($event, index)"
              @dragend="handleTimelineDragEnd"
            >
              <div class="absolute inset-0 flex items-center justify-center text-white text-xs font-medium">
                {{ t('studio.shotNumber', { number: clip.shotSequence }) }}
              </div>
              <div class="absolute bottom-1 right-1 text-xs text-white/80">
                {{ clip.duration }}s
              </div>
              <button
                class="absolute -top-1 -right-1 w-5 h-5 bg-red-500 hover:bg-red-600 text-white rounded-full opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center text-xs"
                @click.stop="removeFromTimeline(index)"
              >
                ×
              </button>
            </div>

            <div
              v-if="draggingFromGallery || videoTrackClips.length === 0"
              class="h-full min-w-32 border-2 border-dashed border-primary-400 dark:border-primary-600 rounded flex items-center justify-center text-primary-500 text-xs"
            >
              {{ t('studio.timelineEmpty') }}
            </div>
          </div>
        </div>

        <!-- Audio Track (placeholder) -->
        <div class="flex-none h-12 flex items-center px-4 border-t border-gray-200 dark:border-gray-700">
          <div class="w-20 flex-shrink-0 text-xs text-gray-500 dark:text-gray-400">
            {{ t('studio.audioTrack') }}
          </div>
          <div class="flex-1 h-8 bg-gray-100 dark:bg-gray-700 rounded opacity-50" />
        </div>
      </div>
    </template>

    <!-- Delete Confirmation Modal -->
    <Teleport to="body">
      <div
        v-if="showDeleteConfirm"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
        @click.self="showDeleteConfirm = false"
      >
        <div class="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-sm p-6">
          <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            {{ t('studio.shot.delete') }}
          </h3>
          <p class="text-gray-600 dark:text-gray-400 mb-6">
            {{ t('studio.shot.deleteConfirm', { sequence: deletingShotSequence }) }}
          </p>
          <div class="flex justify-end gap-3">
            <button class="btn-secondary" @click="showDeleteConfirm = false">
              {{ t('common.cancel') }}
            </button>
            <button class="btn-danger" :disabled="isSaving" @click="handleDeleteShot">
              {{ t('common.delete') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Export Modal -->
    <Teleport to="body">
      <div
        v-if="showExportModal"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
        @click.self="showExportModal = false"
      >
        <div class="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-md p-6">
          <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            {{ t('studio.export.title') }}
          </h3>

          <div class="space-y-4">
            <div>
              <label class="label">{{ t('studio.export.format') }}</label>
              <select v-model="exportSettings.format" class="input w-full">
                <option v-for="f in EXPORT_FORMATS" :key="f.value" :value="f.value">
                  {{ locale === 'zh-CN' ? f.labelZh : f.label }}
                </option>
              </select>
            </div>

            <div>
              <label class="label">{{ t('studio.export.resolution') }}</label>
              <select v-model="exportSettings.resolution" class="input w-full">
                <option v-for="r in EXPORT_RESOLUTIONS" :key="r.value" :value="r.value">
                  {{ locale === 'zh-CN' ? r.labelZh : r.label }}
                </option>
              </select>
            </div>

            <div>
              <label class="label">{{ t('studio.export.fps') }}</label>
              <select v-model="exportSettings.fps" class="input w-full">
                <option v-for="f in EXPORT_FPS" :key="f.value" :value="f.value">
                  {{ locale === 'zh-CN' ? f.labelZh : f.label }}
                </option>
              </select>
            </div>

            <div class="flex items-center gap-2">
              <input
                id="include-audio"
                v-model="exportSettings.includeAudio"
                type="checkbox"
                class="rounded border-gray-300 text-primary-500 focus:ring-primary-500"
              />
              <label for="include-audio" class="text-sm text-gray-700 dark:text-gray-300">
                {{ t('studio.export.includeAudio') }}
              </label>
            </div>
          </div>

          <div class="flex justify-end gap-3 mt-6">
            <button class="btn-secondary" @click="showExportModal = false">
              {{ t('studio.export.cancel') }}
            </button>
            <button class="btn-primary" @click="handleExport">
              {{ t('studio.export.export') }}
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
              {{ t('storyboard.edit.selectAsset') }}
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
              {{ t('storyboard.edit.noAvailableAssets') }}
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
  </div>
</template>

<style scoped>
.studio-view {
  height: 100%;
}
.btn-sm {
  @apply px-2 py-1 text-sm;
}
</style>
