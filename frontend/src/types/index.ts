export interface User {
  id: string
  username: string
  email: string
  isActive: boolean
  balance: number
  createdAt: string
}

export interface Novel {
  id: string
  title: string
  author: string | null
  status: TaskStatus
  workflowStatus: WorkflowStatus
  totalChapters: number
  processedChapters: number
  createdAt: string
  updatedAt: string
}

export interface NovelDetail extends Novel {
  content: string | null
  metadata: Record<string, unknown>
  // 工作流状态检查
  canExtractChapters: boolean
  canExtractCharacters: boolean
  canCreateStoryboard: boolean
  canGenerateVideo: boolean
}

export interface Chapter {
  id: string
  novelId: string
  number: number
  title: string
  status: TaskStatus
  workflowStatus: ChapterWorkflowStatus
  sceneCount: number
  createdAt: string
}

export interface ChapterDetail extends Chapter {
  content: string
  metadata: Record<string, unknown>
}

export interface Character {
  id: string
  novelId: string
  name: string
  description: string | null
  gender: Gender
  voiceProvider: VoiceProvider
  referenceImages: string[]
  createdAt: string
}

export interface Scene {
  id: string
  chapterId: string
  sequence: number
  description: string
  dialogue: string | null
  speakerId: string | null
  imageUrl: string | null
  audioUrl: string | null
  duration: number
  status: TaskStatus
}

export interface Video {
  id: string
  novelId: string
  chapterId: string | null
  title: string
  url: string | null
  duration: number
  resolution: string
  fps: number
  status: TaskStatus
  createdAt: string
}

export type TaskStatus = 'pending' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
export type WorkflowStatus = 'draft' | 'chapters_extracted' | 'characters_extracted' | 'storyboard_ready' | 'generating' | 'completed'
export type ChapterWorkflowStatus = 'pending' | 'characters_extracted' | 'assets_reviewed' | 'storyboard_ready' | 'generating' | 'completed'
export type Gender = 'male' | 'female' | 'other'
export type VoiceProvider = 'edge_tts' | 'azure' | 'openai' | 'fish_speech' | 'custom'

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  pageSize: number
  totalPages: number
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface ApiError {
  detail: string
}

export interface DashboardStats {
  total_novels: number
  total_videos: number
  processing_time: number
  balance: number
  recent_novels: Novel[]
}

