export enum AssetTypeEnum { PERSON = 1, SCENE = 2, ITEM = 3, PRODUCT = 4, STYLE = 5 }
export enum TaskStatusEnum { PENDING = 1, PROCESSING = 2, COMPLETED = 3, FAILED = 4, CANCELLED = 5, QUEUED = 6 }

export interface WorkbenchCapabilities {
  upload_media: boolean
  generate_asset: boolean
  generate_video: boolean
  apply_watermark: boolean
  compose_video: boolean
  prompt_editors?: Array<{
    editor_key: string
    node_kind: 'asset' | 'shot'
    field_key: string
    label: string
    placeholder: string
    hint: string
    allowed_asset_types: string[] | null
    excluded_asset_types: string[] | null
    reference_limits: { image: number; video: number; audio: number }
    allow_prompt_injection: boolean
  }>
  refresh_policy?: {
    poll_interval_ms: number
    poll_max_interval_ms: number
  }
}

export interface Novel { id: number; name: string; author?: string; description?: string; cover?: string; total_chapters?: number; content?: string; tags?: string[] | null; story_outline?: string | null; project_type?: string | null; project_setting?: string | null; storyboard_strategy?: string | null; storyboard_setting?: string | null; created_at: string; updated_at: string }
export interface Chapter { id: number; novel_id: number; number: number; name: string; content?: string; status?: TaskStatusEnum; workflow_status?: number; created_at: string; updated_at: string }
export interface AssetVariant { id: number; asset_id: number; name: string; description?: string; base_traits?: string; chapter_numbers?: number[]; images: string[]; metadata?: Record<string, unknown>; created_at: string; updated_at: string }
export interface Asset { id: number; novel_id: number; asset_type: AssetTypeEnum; canonical_name: string; aliases?: string[]; description?: string; base_traits?: string; main_image?: string; angle_image_1?: string; angle_image_2?: string; image_source?: number; metadata?: Record<string, unknown>; is_global?: boolean; source_chapters?: number[]; last_updated_chapter?: number; variants?: AssetVariant[]; created_at: string; updated_at: string }
export interface AssetGenerationRecord { id: string; status: TaskStatusEnum; images: string[]; error_message?: string; model?: string; clarity?: string; aspect_ratio?: string; output_format?: string; created_at: string; finished_at?: string }
export interface AssetReferencePromptPreview { prompt: string; prompt_language: 'zh' | 'en' }
export interface AssetMergeResult { asset: Asset; removed_asset_id: number; data_source_asset_id: number; image_source_asset_id?: number; summary: string[] }
export interface Scene { id: number; chapter_id?: number; sequence: number; description?: string; prompt?: string; prompt_params?: Record<string, unknown>; metadata?: Record<string, unknown>; duration?: number; status?: TaskStatusEnum; asset_ids?: number[]; assets?: Asset[]; created_at: string; updated_at: string }
export interface Video { id: number; scene_id: number; model_type: number; url?: string; external_task_id?: string; status: TaskStatusEnum; progress?: number; metadata?: Record<string, unknown>; created_at: string; updated_at: string }
export interface WorkbenchBootstrap { chapter: Chapter; assets: Asset[]; scenes: Scene[]; videos: Record<number, Video[]> }
export interface AiTask {
  id: string
  task_type: number
  status: TaskStatusEnum
  request_params?: Record<string, unknown>
  response_data?: Record<string, unknown>
  error_message?: string
  started_at?: string
  finished_at?: string
  created_at: string
  updated_at?: string
}
export type ImageApiProtocol = 'openai_compatible' | 'openrouter_compatible' | 'volcengine_ark'
export type ImageModelType = 'seedream_5_lite' | 'seedream_5_pro' | 'gpt_image_2'
export interface ImageGenerationCapabilities { clarities: string[]; aspect_ratios: string[]; output_formats: string[]; generation_counts: number[]; default_clarity: string; default_aspect_ratio: string; default_output_format: string; default_generation_count: number }
export interface ImageGenerationModel { config_id: number; name: string; model: string; model_type: ImageModelType; concurrency: number; capabilities: ImageGenerationCapabilities }
export type VideoGenerationModelType = 'seedance_2' | 'seedance_2_fast' | 'seedance_2_mini' | 'seedance_2_5'
export interface VideoGenerationCapabilities { resolutions: string[]; aspect_ratios: string[]; aspect_ratios_by_mode: Record<string, string[]>; output_formats: string[]; generation_modes: string[]; duration_min: number; duration_max: number; supports_auto_duration: boolean; supports_audio: boolean; max_reference_images: number; default_resolution: string; default_aspect_ratio: string; default_output_format: string; default_generate_audio: boolean }
export interface VideoGenerationModel { config_id: number; name: string; model: string; model_type: VideoGenerationModelType; concurrency: number; capabilities: VideoGenerationCapabilities }
export interface AiModelConfig { id: number; task_type: number; task_types?: number[]; name: string; base_url?: string; api_key?: string; model?: string; api_protocol: ImageApiProtocol; image_model_type?: ImageModelType | null; video_model_type?: VideoGenerationModelType | null; is_active: boolean; concurrency: number; supports_json_output: boolean; max_context_characters?: number | null; created_at: string; updated_at: string }
export interface GeneralConfig { id: number; prompt_language: 'zh' | 'en'; created_at: string; updated_at: string }
export interface AudioReference { id: number; nickname: string; gender: string; audio_url: string; avatar_url: string; asset_id: string; is_active: boolean; created_at: string; updated_at: string }
export interface DigitalHuman { id: number; country: string; age: number; gender: string; occupation: string; asset_id: string; image_url: string; is_active: boolean; created_at: string; updated_at: string }
export interface EnumItem { value: number; label: string }
export interface ConfigEnumItem { value: string | number; label: string; name?: string }
export interface AllEnums {
  task_status: EnumItem[]
  asset_type: EnumItem[]
  image_source: EnumItem[]
  workflow_status: EnumItem[]
  ai_task_type: EnumItem[]
  video_model_type: ConfigEnumItem[]
  image_model_type: ConfigEnumItem[]
  [key: string]: ConfigEnumItem[]
}
export interface PaginationResponse<T> { code: number; message: string; data: { items: T[]; pagination: { total: number; page: number; page_size: number; pages: number } } }
export interface SingleResponse<T> { code: number; message: string; data: T }
