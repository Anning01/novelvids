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

export interface NovelMeta {
  id: number
  name: string
  author?: string
  description?: string
  cover?: string
  total_chapters?: number
  tags?: string[] | null
  style_key?: string | null
  video_model_config_id?: number | null
  storyboard_strategy?: string | null
  storyboard_setting?: string | null
  content_length: number
  created_at: string
  updated_at: string
}
export interface StoryboardStrategy { key: string; name: string; description: string; is_default: boolean }
export interface Novel { id: number; name: string; author?: string; style_key?: string | null; video_model_config_id?: number | null; description?: string; cover?: string; total_chapters?: number; content?: string; tags?: string[] | null; story_outline?: string | null; project_type?: string | null; project_setting?: string | null; storyboard_strategy?: string | null; storyboard_setting?: string | null; created_at: string; updated_at: string }
export interface Chapter { id: number; novel_id: number; number: number; name: string; content?: string; status?: TaskStatusEnum; workflow_status?: number; created_at: string; updated_at: string }
export interface AssetVariant { id: number; asset_id: number; name: string; description?: string; base_traits?: string; chapter_numbers?: number[]; images: string[]; metadata?: Record<string, unknown>; created_at: string; updated_at: string }
export interface AssetVariantDraft { id: number | null; name: string; description: string; chapter_numbers: number[]; is_new: boolean }
export interface Asset { id: number; novel_id: number; asset_type: AssetTypeEnum; canonical_name: string; aliases?: string[]; description?: string; base_traits?: string; main_image?: string; angle_image_1?: string; angle_image_2?: string; image_source?: number; metadata?: Record<string, unknown>; is_global?: boolean; source_chapters?: number[]; last_updated_chapter?: number; variants?: AssetVariant[]; created_at: string; updated_at: string }
export interface AssetGenerationRecord { id: string; status: TaskStatusEnum; is_current?: boolean; images: string[]; error_message?: string; model?: string; clarity?: string; aspect_ratio?: string; output_format?: string; created_at: string; finished_at?: string }
export interface AssetActiveGeneration { asset_id: number; task_id: string; status: TaskStatusEnum }
export interface AssetReferencePromptPreview { prompt: string; prompt_language: 'zh' | 'en' }
export interface AssetMergeResult { asset: Asset; removed_asset_id: number; data_source_asset_id: number; image_source_asset_id?: number; summary: string[] }
export interface Scene { id: number; chapter_id?: number; sequence: number; description?: string; prompt?: string; prompt_params?: Record<string, unknown>; metadata?: Record<string, unknown>; duration?: number; status?: TaskStatusEnum; asset_ids?: number[]; assets?: Asset[]; created_at: string; updated_at: string }
export interface Video { id: number; scene_id: number; model_type: number; url?: string; external_task_id?: string; status: TaskStatusEnum; progress?: number; metadata?: Record<string, unknown>; created_at: string; updated_at: string }
export interface VideoMergeResult { chapter_id: number; merged_url: string; video_count: number; total_duration: number }
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
export type ImageApiProtocol = 'openai_compatible' | 'openrouter_compatible' | 'volcengine_ark' | 'minimax'
export type ImageModelType = 'seedream_5_lite' | 'seedream_5_pro' | 'gpt_image_2'
export interface ImageGenerationCapabilities { clarities: string[]; aspect_ratios: string[]; output_formats: string[]; generation_counts: number[]; default_clarity: string; default_aspect_ratio: string; default_output_format: string; default_generation_count: number }
export interface ImageGenerationModel { config_id: number; name: string; model: string; model_type: ImageModelType; concurrency: number; pricing?: ModelPricing | null; capabilities: ImageGenerationCapabilities }
export type VideoGenerationModelType = 'seedance_2' | 'seedance_2_fast' | 'seedance_2_mini' | 'seedance_2_5' | 'minimax_h3'
export interface VideoReferenceMedia { type: 'image' | 'video'; url: string; mention_url?: string; name?: string; content_type?: string; size_bytes?: number; width?: number; height?: number; duration?: number; fps?: number; codec?: string }
export interface VideoInputImageReference {
  number: number
  url: string
  label: string
  source: 'asset' | 'upload'
  assetId?: number
  mediaIndex?: number
  assetImageIndex?: number
}
export interface VideoGenerationCapabilities {
  resolutions: string[]
  aspect_ratios: string[]
  aspect_ratios_by_mode: Record<string, string[]>
  output_formats: string[]
  generation_modes: string[]
  duration_min: number
  duration_max: number
  supports_auto_duration: boolean
  supports_audio: boolean
  supports_return_last_frame: boolean
  max_reference_images: number
  max_reference_videos: number
  max_reference_audios: number
  reference_video_duration_max: number
  reference_video_total_duration_max: number
  reference_audio_duration_max: number
  reference_audio_total_duration_max: number
  reference_image_formats: string[]
  reference_video_formats: string[]
  reference_video_codecs: string[]
  reference_video_audio_codecs: string[]
  reference_video_resolutions: string[]
  reference_image_max_size_mb: number
  reference_video_max_size_mb: number
  reference_media_duration_min: number
  reference_media_ratio_min: number
  reference_media_ratio_max: number
  reference_media_side_min: number
  reference_media_side_max: number
  reference_video_pixels_min: number
  reference_video_pixels_max: number
  reference_video_fps_min: number
  reference_video_fps_max: number
  default_resolution: string
  default_aspect_ratio: string
  default_output_format: string
  default_generate_audio: boolean
}
export interface VideoGenerationModel { config_id: number; name: string; model: string; model_type: VideoGenerationModelType; concurrency: number; pricing?: ModelPricing | null; capabilities: VideoGenerationCapabilities }
export interface ModelPricing {
  type: 'text' | 'image' | 'video'
  currency: string
  input_price_per_1m?: number
  output_price_per_1m?: number
  prices?: Record<string, number>
  input_image?: { first_free: number; price_per_image: number }
  video_reference_prices?: Record<string, number>
  billing_unit?: 'token' | 'second'
  discount?: number
  discount_description?: string
}
export interface GenerationCapabilities {
  image: Record<string, string[]>
  video: Record<string, string[]>
  video_pricing?: Partial<Record<VideoGenerationModelType, ModelPricing>>
}
export interface AiModelConfig { id: number; task_type: number; task_types?: number[]; name: string; base_url?: string; api_key?: string; model?: string; api_protocol: ImageApiProtocol; image_model_type?: ImageModelType | null; video_model_type?: VideoGenerationModelType | null; is_active: boolean; concurrency: number; supports_json_output: boolean; max_context_characters?: number | null; thinking?: 'enabled' | 'disabled' | null; max_tokens?: number | null; pricing?: ModelPricing | null; scope?: 'official' | 'team'; team_id?: number | null; created_at: string; updated_at: string }
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

// ---- 登录与团队（AUTH_ENABLED=true 时生效） ----

export type TeamRole = 'admin' | 'creator' | 'viewer'

export interface AuthUser {
  id: number
  username: string
  nickname: string
  avatar_url: string
  is_super_admin: boolean
  created_at?: string
}

export interface Membership {
  team_id: number
  team_name: string
  role: TeamRole
  status?: number
  total_cost?: number | string
  cost_limit?: number | string | null
  team_balance?: number | string | null
  joined_at?: string
}

export interface AuthMe {
  user: AuthUser
  memberships: Membership[]
  is_super_admin: boolean
  total_cost?: number | string
}

export interface AuthStatus { enabled: boolean }
export interface LoginResult { token: string; user: AuthUser }

export interface TeamItem {
  id: number
  name: string
  balance: number
  model_config_source: 'official' | 'custom'
  status: number
  member_limit?: number | null
  owner_user_id?: number | null
  owner_username?: string
  member_count: number
  created_at?: string
  updated_at?: string
}

export interface UserItem {
  id: number
  username: string
  nickname: string
  is_super_admin: boolean
  status: number
  created_at?: string
  total_cost?: number | string
  team_count?: number
}

export interface VisualStyleItem { key: string; label: string }

export interface UploadPolicy {
  direct: boolean
  provider?: string
  key?: string
  upload_url?: string
  fields?: Record<string, string>
  public_url?: string
  filename?: string
}
export interface UploadResult {
  filename: string
  original_filename: string
  content_type: string
  file_path: string
  url?: string
  key?: string
  message?: string
  text_content?: string
  chapter_validation?: { valid: boolean; chapter_count: number; text_length: number; message: string } | null
}
export interface OssFinalizeResult {
  filename: string
  url: string
  key: string
  text_content?: string
  chapter_validation?: { valid: boolean; chapter_count: number; text_length: number; message: string } | null
}

export interface UserStats {
  user_count: number
  user_total_cost: number
  team_count: number
  team_balance_total: number
}

export interface MemberItem {
  user_id: number
  username: string
  nickname: string
  role: TeamRole
  status: number
  total_cost: number | string
  cost_limit?: number | string | null
}

export interface InviteItem {
  token: string
  team_id: number
  team_name: string
  role: TeamRole
  expires_at: string
}
export interface BillingRecord {
  id: number
  novel_id: number
  task_type: number
  billing_type: 'text' | 'image' | 'video'
  ai_task_id?: string | null
  video_id?: number | null
  model_config_id?: number | null
  model_name?: string | null
  model: string
  model_type?: string | null
  pricing_snapshot?: Record<string, unknown> | null
  usage: Record<string, unknown>
  cost: number
  currency: string
  status: number
  duration_seconds?: number | null
  cost_source?: 'balance' | 'team_key' | string
  team_id?: number | null
  user_id?: number | null
  created_at: string
  updated_at: string
}
export interface BillingSummary {
  total_cost: number
  total_records: number
  by_billing_type: Array<{ billing_type: string; cost: number }>
  by_task_type: Array<{ task_type: number; cost: number }>
  by_model: Array<{ model: string; cost: number }>
  daily_trend: Array<{ date: string; cost: number }>
}
export interface BillingProject { novel_id: number; novel_name: string; total_cost: number; record_count: number }
export interface BillingProjectDetail {
  novel_id: number
  novel_name: string
  total_cost: number
  record_count: number
  by_task_type: Array<{ task_type: number; cost: number }>
}
