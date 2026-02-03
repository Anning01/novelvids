/**
 * Studio View Type Definitions
 *
 * Types for the video composition studio - the final step
 * in the novel-to-video workflow.
 */

import type { Shot } from '@/api/storyboard'

/** Supported video generation models */
export type VideoModel = 'vidu' | 'doubao' | 'veo' | 'kling' | 'sora'

/** Video clip generation status */
export type ClipStatus = 'pending' | 'generating' | 'completed' | 'failed'

/**
 * A generated video clip for a shot.
 * Each shot can have multiple clips (gacha/lottery mechanic).
 */
export interface VideoClip {
  id: string
  shotSequence: number
  model: VideoModel
  status: ClipStatus
  progress: number
  videoUrl: string | null
  thumbnailUrl: string | null
  duration: number
  createdAt: string
  prompt: string
  negativePrompt: string | null
  error: string | null
}

/**
 * Extended shot with studio-specific data.
 * Includes the list of generated clips and selected clip ID.
 */
export interface StudioShot extends Shot {
  clips: VideoClip[]
  selectedClipId: string | null
}

/**
 * A clip placed on the timeline.
 * References a VideoClip by ID.
 */
export interface TimelineClip {
  id: string
  clipId: string
  shotSequence: number
  startTime: number
  duration: number
  thumbnailUrl: string | null
}

/**
 * A track on the timeline (video or audio).
 */
export interface TimelineTrack {
  id: string
  type: 'video' | 'audio'
  clips: TimelineClip[]
}

/**
 * The studio project state for a chapter.
 */
export interface StudioProject {
  chapterId: string
  shots: StudioShot[]
  timeline: TimelineTrack[]
  totalDuration: number
}

/**
 * Video generation request parameters.
 */
export interface GenerateVideoRequest {
  shotSequence: number
  model: VideoModel
  duration: number
}

/**
 * Final video composition request.
 */
export interface ComposeVideoRequest {
  timeline: TimelineTrack[]
  outputFormat: 'mp4' | 'webm'
  resolution: '720p' | '1080p' | '4k'
}

/**
 * Export settings for the final video.
 */
export interface ExportSettings {
  format: 'mp4' | 'webm'
  resolution: '720p' | '1080p' | '4k'
  fps: 24 | 30 | 60
  includeAudio: boolean
}
