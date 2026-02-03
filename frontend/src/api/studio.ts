/**
 * Studio API Client
 *
 * API functions for the video composition studio.
 */

import api from './client'
import type {
  VideoClip,
  StudioShot,
  StudioProject,
  GenerateVideoRequest,
  ComposeVideoRequest,
  TimelineTrack,
  VideoModel,
} from '@/types/studio'
import type { StoryboardResponse } from './storyboard'
import { getStoryboard } from './storyboard'

// ============== Types for API Responses ==============

interface VideoTaskResponse {
  task_id: string
  platform: string
  status: 'pending' | 'processing' | 'succeeded' | 'failed'
  progress: number
  video_url: string | null
  error: string | null
  shot_sequence: number | null
}

export interface GenerateVideoResult {
  clip: VideoClip
  taskId: string
  isComplete: boolean
}

// ============== Helper Functions ==============

let clipIdCounter = 1

function taskResponseToClip(
  response: VideoTaskResponse,
  model: VideoModel,
  duration: number,
  prompt: string,
  negativePrompt: string | null
): VideoClip {
  const id = `clip-${clipIdCounter++}-${Date.now()}`
  const statusMap: Record<string, VideoClip['status']> = {
    pending: 'pending',
    processing: 'generating',
    succeeded: 'completed',
    failed: 'failed',
  }

  return {
    id,
    shotSequence: response.shot_sequence ?? 0,
    model,
    status: statusMap[response.status] || 'pending',
    progress: response.progress,
    videoUrl: response.video_url,
    thumbnailUrl: null,
    duration,
    createdAt: new Date().toISOString(),
    prompt,
    negativePrompt,
    error: response.error,
  }
}

// ============== API Functions ==============

/**
 * Get studio project data for a chapter.
 * Loads storyboard and converts to studio format.
 */
export async function getStudioProject(chapterId: string): Promise<StudioProject> {
  const storyboard: StoryboardResponse = await getStoryboard(chapterId)

  const shots: StudioShot[] = storyboard.shots.map(shot => {
    const clips: VideoClip[] = []
    let selectedClipId: string | null = null

    // If shot has a completed video, create a clip for it
    // Note: backend uses 'succeeded', handle all possible success status values
    const isCompleted = ['success', 'completed', 'succeeded'].includes(shot.video_task_status || '')
    if (shot.video_url && isCompleted) {
      const clipId = `clip-${shot.sequence}-${Date.now()}`
      clips.push({
        id: clipId,
        shotSequence: shot.sequence,
        model: (shot.video_task_platform as VideoModel) || 'vidu',
        status: 'completed',
        progress: 100,
        videoUrl: shot.video_url,
        thumbnailUrl: null,
        duration: shot.technical?.duration || 6,
        createdAt: new Date().toISOString(),
        prompt: shot.platform_prompt || shot.description_cn,
        negativePrompt: null,
        error: null,
      })
      selectedClipId = clipId
    }

    return {
      ...shot,
      clips,
      selectedClipId,
    }
  })

  return {
    chapterId,
    shots,
    timeline: [
      { id: 'video-track', type: 'video', clips: [] },
      { id: 'audio-track', type: 'audio', clips: [] },
    ],
    totalDuration: storyboard.total_duration,
  }
}

/**
 * Generate a new video clip for a shot.
 * Calls the real backend API and starts a video generation task.
 * Returns both the clip and task information for tracking.
 */
export async function generateVideoClip(
  chapterId: string,
  request: GenerateVideoRequest,
  prompt: string,
  negativePrompt: string | null
): Promise<GenerateVideoResult> {
  const response = await api.post<VideoTaskResponse>('/generate/video', {
    chapter_id: chapterId,
    shot_sequence: request.shotSequence,
    platform: request.model,
    duration: request.duration,
    aspect_ratio: '16:9',
  })

  const task = response.data
  const taskId = task.task_id

  // If task started successfully, poll until completion or timeout
  if (task.status === 'pending' || task.status === 'processing') {
    const completedTask = await pollVideoTaskUntilComplete(
      taskId,
      request.model,
      60000, // 60 second timeout
      3000,
      chapterId,
      request.shotSequence
    )
    const clip = taskResponseToClip(completedTask, request.model, request.duration, prompt, negativePrompt)
    const isComplete = completedTask.status === 'succeeded'
    return { clip, taskId, isComplete }
  }

  const clip = taskResponseToClip(task, request.model, request.duration, prompt, negativePrompt)
  const isComplete = task.status === 'succeeded'
  return { clip, taskId, isComplete }
}

/**
 * Poll video task status until completion.
 */
export async function pollVideoTaskUntilComplete(
  taskId: string,
  platform: string,
  timeoutMs: number = 60000,
  intervalMs: number = 3000,
  chapterId?: string,
  shotSequence?: number
): Promise<VideoTaskResponse> {
  const startTime = Date.now()

  while (Date.now() - startTime < timeoutMs) {
    const response = await api.get<VideoTaskResponse>(`/generate/video/${taskId}`, {
      params: {
        platform,
        chapter_id: chapterId,
        shot_sequence: shotSequence,
      },
    })

    const task = response.data

    if (task.status === 'succeeded' || task.status === 'failed') {
      return task
    }

    await new Promise(resolve => setTimeout(resolve, intervalMs))
  }

  // Timeout - return last known status
  const response = await api.get<VideoTaskResponse>(`/generate/video/${taskId}`, {
    params: {
      platform,
      chapter_id: chapterId,
      shot_sequence: shotSequence,
    },
  })
  return response.data
}

/**
 * Get video task status (single poll).
 */
export async function getVideoTaskStatus(
  taskId: string,
  platform: string = 'vidu',
  chapterId?: string,
  shotSequence?: number
): Promise<{
  status: 'pending' | 'running' | 'completed' | 'failed'
  progress: number
  videoUrl: string | null
  error: string | null
}> {
  const response = await api.get<VideoTaskResponse>(`/generate/video/${taskId}`, {
    params: {
      platform,
      chapter_id: chapterId,
      shot_sequence: shotSequence,
    },
  })

  const task = response.data
  const statusMap: Record<string, 'pending' | 'running' | 'completed' | 'failed'> = {
    pending: 'pending',
    processing: 'running',
    succeeded: 'completed',
    failed: 'failed',
  }

  return {
    status: statusMap[task.status] || 'pending',
    progress: task.progress,
    videoUrl: task.video_url,
    error: task.error,
  }
}

/**
 * Cancel/clear a video generation task for a shot.
 */
export async function cancelVideoTask(
  chapterId: string,
  shotSequence: number
): Promise<void> {
  await api.delete(`/generate/video/${chapterId}/${shotSequence}`)
}

/**
 * Get all clips for a shot.
 * Note: Clips are currently managed locally on the frontend.
 */
export async function getShotClips(
  _chapterId: string,
  _shotSequence: number
): Promise<VideoClip[]> {
  // TODO: Implement backend storage for clips
  return []
}

/**
 * Select a clip for a shot.
 * Note: State is currently managed locally on the frontend.
 */
export async function selectClipForShot(
  _chapterId: string,
  _shotSequence: number,
  _clipId: string
): Promise<void> {
  // TODO: Implement backend persistence
  await new Promise(resolve => setTimeout(resolve, 100))
}

/**
 * Delete a clip.
 * Note: State is currently managed locally on the frontend.
 */
export async function deleteClip(
  _chapterId: string,
  _clipId: string
): Promise<void> {
  // TODO: Implement backend deletion
  await new Promise(resolve => setTimeout(resolve, 100))
}

/**
 * Update timeline arrangement.
 * Note: State is currently managed locally on the frontend.
 */
export async function updateTimeline(
  _chapterId: string,
  _timeline: TimelineTrack[]
): Promise<void> {
  // TODO: Implement backend persistence
  await new Promise(resolve => setTimeout(resolve, 100))
}

/**
 * Compose final video.
 * Note: Not yet implemented on the backend.
 */
export async function composeVideo(
  _chapterId: string,
  _request: ComposeVideoRequest
): Promise<{ taskId: string }> {
  // TODO: Implement backend composition
  await new Promise(resolve => setTimeout(resolve, 500))
  return { taskId: `compose-task-${Date.now()}` }
}

// ============== Constants ==============

export const VIDEO_MODELS = [
  { value: 'vidu' as const, label: 'Vidu Q2', labelZh: 'Vidu Q2', description: 'Fine expressions, smooth motion', descriptionZh: '细腻表情，平滑运动', disabled: false },
  { value: 'doubao' as const, label: 'Doubao Seedance', labelZh: '豆包 Seedance', description: 'Volcano Engine video model', descriptionZh: '火山引擎视频模型', disabled: false },
  { value: 'veo' as const, label: 'Veo 3.1', labelZh: 'Veo 3.1', description: 'Native audio, multi-reference', descriptionZh: '原生音频，多参考图', disabled: true },
  { value: 'kling' as const, label: 'Kling 2.5', labelZh: 'Kling 2.5', description: 'Cinematic action videos', descriptionZh: '电影感动作视频', disabled: true },
  { value: 'sora' as const, label: 'Sora 2', labelZh: 'Sora 2', description: 'Physics-aware, complex scenes', descriptionZh: '物理感知，复杂场景', disabled: true },
] as const

export const EXPORT_RESOLUTIONS = [
  { value: '720p' as const, label: '720p (HD)', labelZh: '720p (高清)' },
  { value: '1080p' as const, label: '1080p (Full HD)', labelZh: '1080p (全高清)' },
  { value: '4k' as const, label: '4K (Ultra HD)', labelZh: '4K (超高清)' },
] as const

export const EXPORT_FORMATS = [
  { value: 'mp4' as const, label: 'MP4 (H.264)', labelZh: 'MP4 (H.264)' },
  { value: 'webm' as const, label: 'WebM (VP9)', labelZh: 'WebM (VP9)' },
] as const

export const EXPORT_FPS = [
  { value: 24 as const, label: '24 fps (Film)', labelZh: '24 帧 (电影)' },
  { value: 30 as const, label: '30 fps (Standard)', labelZh: '30 帧 (标准)' },
  { value: 60 as const, label: '60 fps (Smooth)', labelZh: '60 帧 (流畅)' },
] as const
