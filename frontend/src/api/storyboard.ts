/**
 * 分镜 API 客户端
 *
 * 使用任务模式进行分镜生成，支持轮询查询进度
 */

import api from './client'

// ============== 任务类型定义 ==============

/** 任务状态 */
export type TaskStatus = 'pending' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'

/** 任务响应 */
export interface StoryboardTask {
  id: string
  chapter_id: string
  status: TaskStatus
  progress: number
  message: string | null
  error: string | null
  result: {
    shot_count?: number
    total_duration?: number
    warnings?: string[]
    retry_task_id?: string
  } | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

// ============== 分镜类型定义 ==============

/** 分镜生成请求 */
export interface StoryboardGenerateRequest {
  max_shot_duration?: number
  target_platform?: 'vidu' | 'doubao'
  style_preset?: string
  aspect_ratio?: string
  include_audio?: boolean
}

/** 相机设置 */
export interface CameraSettings {
  shot_size: string
  camera_angle: string
  camera_movement: string
  movement_speed: string
  lens_type: string
  depth_of_field: string
  focus_target: string | null
}

/** 主体与动作 */
export interface SubjectAction {
  subject_type: 'person' | 'scene' | 'item' | 'multiple'
  subject_description: string
  asset_refs: string[]
  action: string
  action_intensity: string
  emotion: string | null
  body_language: string | null
}

/** 环境设置 */
export interface EnvironmentSettings {
  location: string
  scene_asset_ref: string | null
  time_of_day: string
  weather: string | null
  lighting: string
  lighting_details: string | null
  atmosphere_elements: string[]
}

/** 风格设置 */
export interface StyleSettings {
  video_style: string
  mood: string
  color_grading: string | null
  film_grain: boolean
  contrast: string
  saturation: string
}

/** 音频设置 */
export interface AudioSettings {
  dialogue: string | null
  dialogue_speaker: string | null
  dialogue_tone: string | null
  sound_effects: string[]
  ambient_sounds: string[]
  background_music: string | null
  music_volume: string
}

/** 技术参数 */
export interface TechnicalSettings {
  duration: number
  aspect_ratio: string
  motion_speed: string
  resolution: string
  fps: number
}

/** 负面提示词 */
export interface NegativePrompt {
  avoid_elements: string[]
  avoid_artifacts: boolean
  avoid_text: boolean
}

/** 单个分镜 */
export interface Shot {
  sequence: number
  name: string | null
  description_cn: string
  source_text: string | null
  source_line_start: number | null
  source_line_end: number | null
  camera: CameraSettings
  subject: SubjectAction
  environment: EnvironmentSettings
  style: StyleSettings
  audio: AudioSettings
  technical: TechnicalSettings
  negative: NegativePrompt
  reference_images: string[]
  start_frame: string | null
  end_frame: string | null
  transition_in: string | null
  transition_out: string | null
  // 平台优化提示词
  platform_prompt: string | null
  // 视频生成任务状态
  video_task_id: string | null
  video_task_platform: string | null
  video_task_status: 'pending' | 'processing' | 'running' | 'queued' | 'success' | 'completed' | 'succeeded' | 'failed' | null
  video_task_progress: number
  video_url: string | null
  video_error: string | null
}

/** 分镜脚本响应 */
export interface StoryboardResponse {
  chapter_id: string
  chapter_number: number
  chapter_title: string
  shots: Shot[]
  total_duration: number
  shot_count: number
}

/** 分镜更新请求 */
export interface ShotUpdateRequest {
  name?: string
  description_cn?: string
  camera?: Partial<CameraSettings>
  subject?: Partial<SubjectAction>
  environment?: Partial<EnvironmentSettings>
  style?: Partial<StyleSettings>
  audio?: Partial<AudioSettings>
  technical?: Partial<TechnicalSettings>
  negative?: Partial<NegativePrompt>
  transition_in?: string
  transition_out?: string
}

/** 分镜提示词 */
export interface ShotPrompt {
  sequence: number
  prompt: string
  negative_prompt: string
  platform: string
}

/** 分镜提示词响应 */
export interface StoryboardPromptsResponse {
  chapter_id: string
  platform: string
  prompts: ShotPrompt[]
}

// ============== 任务 API 函数 ==============

/**
 * 启动分镜生成任务
 * 返回任务对象，前端通过轮询 getTaskStatus 查询进度
 */
export async function startGenerateStoryboard(
  chapterId: string,
  request: StoryboardGenerateRequest = {}
): Promise<StoryboardTask> {
  const response = await api.post(`/storyboard/chapters/${chapterId}/generate`, request)
  return response.data
}

/**
 * 获取任务状态
 */
export async function getTaskStatus(taskId: string): Promise<StoryboardTask> {
  const response = await api.get(`/storyboard/tasks/${taskId}`)
  return response.data
}

/**
 * 获取章节的最新任务
 */
export async function getChapterTask(chapterId: string): Promise<StoryboardTask | null> {
  const response = await api.get(`/storyboard/chapters/${chapterId}/task`)
  return response.data
}

/**
 * 轮询分镜任务直到完成
 * @param taskId 任务ID
 * @param onProgress 进度回调
 * @param interval 轮询间隔（毫秒）
 * @param maxAttempts 最大尝试次数
 */
export async function pollStoryboardTaskUntilComplete(
  taskId: string,
  onProgress?: (task: StoryboardTask) => void,
  interval: number = 1500,
  maxAttempts: number = 120
): Promise<StoryboardTask> {
  let attempts = 0

  while (attempts < maxAttempts) {
    const task = await getTaskStatus(taskId)

    if (onProgress) {
      onProgress(task)
    }

    if (task.status === 'completed' || task.status === 'failed' || task.status === 'cancelled') {
      return task
    }

    attempts++
    await new Promise(resolve => setTimeout(resolve, interval))
  }

  throw new Error('Task polling timeout')
}

// ============== 分镜数据 API 函数 ==============

/**
 * 获取章节的分镜脚本
 */
export async function getStoryboard(chapterId: string): Promise<StoryboardResponse> {
  const response = await api.get(`/storyboard/chapters/${chapterId}`)
  return response.data
}

/**
 * 更新单个分镜
 */
export async function updateShot(
  chapterId: string,
  sequence: number,
  update: ShotUpdateRequest
): Promise<Shot> {
  const response = await api.put(`/storyboard/chapters/${chapterId}/shots/${sequence}`, update)
  return response.data
}

/**
 * 删除单个分镜
 */
export async function deleteShot(
  chapterId: string,
  sequence: number
): Promise<{ message: string; shot_count: number }> {
  const response = await api.delete(`/storyboard/chapters/${chapterId}/shots/${sequence}`)
  return response.data
}

/**
 * 添加新分镜
 */
export async function addShot(
  chapterId: string,
  shot: Partial<Shot>,
  afterSequence?: number
): Promise<Shot> {
  const params = afterSequence !== undefined ? { after_sequence: afterSequence } : {}
  const response = await api.post(`/storyboard/chapters/${chapterId}/shots`, shot, { params })
  return response.data
}

/**
 * 获取分镜的视频生成提示词
 */
export async function getStoryboardPrompts(
  chapterId: string,
  platform: 'vidu' | 'doubao' | 'veo' | 'kling' | 'sora' = 'vidu'
): Promise<StoryboardPromptsResponse> {
  const response = await api.get(`/storyboard/chapters/${chapterId}/prompts`, {
    params: { platform },
  })
  return response.data
}

// ============== 枚举值常量（用于前端选择器）==============

export const SHOT_SIZES = [
  { value: 'extreme_close_up', label: '特写', labelEn: 'Extreme Close-up' },
  { value: 'close_up', label: '近景', labelEn: 'Close-up' },
  { value: 'medium_close_up', label: '中近景', labelEn: 'Medium Close-up' },
  { value: 'medium_shot', label: '中景', labelEn: 'Medium Shot' },
  { value: 'cowboy_shot', label: '牛仔镜头', labelEn: 'Cowboy Shot' },
  { value: 'medium_long_shot', label: '中远景', labelEn: 'Medium Long Shot' },
  { value: 'full_shot', label: '全景', labelEn: 'Full Shot' },
  { value: 'long_shot', label: '远景', labelEn: 'Long Shot' },
  { value: 'extreme_long_shot', label: '大远景', labelEn: 'Extreme Long Shot' },
  { value: 'establishing_shot', label: '建立镜头', labelEn: 'Establishing Shot' },
]

export const CAMERA_ANGLES = [
  { value: 'eye_level', label: '平视', labelEn: 'Eye Level' },
  { value: 'low_angle', label: '仰拍', labelEn: 'Low Angle' },
  { value: 'high_angle', label: '俯拍', labelEn: 'High Angle' },
  { value: 'birds_eye', label: '鸟瞰', labelEn: "Bird's Eye" },
  { value: 'worms_eye', label: '蚂蚁视角', labelEn: "Worm's Eye" },
  { value: 'dutch_angle', label: '荷兰角', labelEn: 'Dutch Angle' },
  { value: 'over_the_shoulder', label: '过肩', labelEn: 'Over the Shoulder' },
  { value: 'pov', label: '第一人称', labelEn: 'POV' },
]

export const CAMERA_MOVEMENTS = [
  { value: 'static', label: '静态', labelEn: 'Static' },
  { value: 'pan_left', label: '左摇', labelEn: 'Pan Left' },
  { value: 'pan_right', label: '右摇', labelEn: 'Pan Right' },
  { value: 'tilt_up', label: '上摇', labelEn: 'Tilt Up' },
  { value: 'tilt_down', label: '下摇', labelEn: 'Tilt Down' },
  { value: 'dolly_in', label: '推镜头', labelEn: 'Dolly In' },
  { value: 'dolly_out', label: '拉镜头', labelEn: 'Dolly Out' },
  { value: 'truck_left', label: '左移', labelEn: 'Truck Left' },
  { value: 'truck_right', label: '右移', labelEn: 'Truck Right' },
  { value: 'tracking', label: '跟踪', labelEn: 'Tracking' },
  { value: 'orbit', label: '环绕', labelEn: 'Orbit' },
  { value: 'handheld', label: '手持', labelEn: 'Handheld' },
  { value: 'steadicam', label: '稳定器', labelEn: 'Steadicam' },
  { value: 'crane_up', label: '升镜头', labelEn: 'Crane Up' },
  { value: 'crane_down', label: '降镜头', labelEn: 'Crane Down' },
  { value: 'whip_pan', label: '急摇', labelEn: 'Whip Pan' },
  { value: 'push_in', label: '缓推', labelEn: 'Push In' },
  { value: 'pull_back', label: '缓拉', labelEn: 'Pull Back' },
]

export const VIDEO_STYLES = [
  { value: 'cinematic', label: '电影感', labelEn: 'Cinematic' },
  { value: 'photorealistic', label: '照片写实', labelEn: 'Photorealistic' },
  { value: 'anime', label: '动漫', labelEn: 'Anime' },
  { value: 'cartoon', label: '卡通', labelEn: 'Cartoon' },
  { value: 'noir', label: '黑色电影', labelEn: 'Noir' },
  { value: 'vintage', label: '复古', labelEn: 'Vintage' },
  { value: 'documentary', label: '纪录片', labelEn: 'Documentary' },
  { value: 'fantasy', label: '奇幻', labelEn: 'Fantasy' },
  { value: 'sci_fi', label: '科幻', labelEn: 'Sci-Fi' },
]

export const MOODS = [
  { value: 'peaceful', label: '平和', labelEn: 'Peaceful' },
  { value: 'tense', label: '紧张', labelEn: 'Tense' },
  { value: 'romantic', label: '浪漫', labelEn: 'Romantic' },
  { value: 'melancholic', label: '忧郁', labelEn: 'Melancholic' },
  { value: 'mysterious', label: '神秘', labelEn: 'Mysterious' },
  { value: 'joyful', label: '欢快', labelEn: 'Joyful' },
  { value: 'dramatic', label: '戏剧性', labelEn: 'Dramatic' },
  { value: 'epic', label: '史诗', labelEn: 'Epic' },
  { value: 'intimate', label: '亲密', labelEn: 'Intimate' },
  { value: 'suspenseful', label: '悬疑', labelEn: 'Suspenseful' },
]

export const LIGHTING_STYLES = [
  { value: 'natural', label: '自然光', labelEn: 'Natural' },
  { value: 'golden_hour', label: '黄金时刻', labelEn: 'Golden Hour' },
  { value: 'blue_hour', label: '蓝调时刻', labelEn: 'Blue Hour' },
  { value: 'high_key', label: '高调光', labelEn: 'High Key' },
  { value: 'low_key', label: '低调光', labelEn: 'Low Key' },
  { value: 'dramatic', label: '戏剧光', labelEn: 'Dramatic' },
  { value: 'backlit', label: '逆光', labelEn: 'Backlit' },
  { value: 'neon', label: '霓虹', labelEn: 'Neon' },
  { value: 'moonlight', label: '月光', labelEn: 'Moonlight' },
  { value: 'volumetric', label: '体积光', labelEn: 'Volumetric' },
]

export const ASPECT_RATIOS = [
  { value: '16:9', label: '16:9 横屏', labelEn: '16:9 Landscape' },
  { value: '9:16', label: '9:16 竖屏', labelEn: '9:16 Portrait' },
  { value: '1:1', label: '1:1 方形', labelEn: '1:1 Square' },
  { value: '21:9', label: '21:9 超宽', labelEn: '21:9 Ultrawide' },
  { value: '2.39:1', label: '2.39:1 宽银幕', labelEn: '2.39:1 Anamorphic' },
]

export const TARGET_PLATFORMS = [
  { value: 'vidu', label: 'Vidu Q2', description: '参考图格式 @id，细腻表情、平滑镜头运动' },
  { value: 'doubao', label: '豆包 Seedance', description: '参考图格式 [图N]，火山引擎视频模型' },
]
