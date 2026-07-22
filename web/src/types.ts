export enum AssetTypeEnum { PERSON = 1, SCENE = 2, ITEM = 3 }
export enum TaskStatusEnum { PENDING = 1, PROCESSING = 2, COMPLETED = 3, FAILED = 4, CANCELLED = 5, QUEUED = 6 }

export interface Novel { id: number; name: string; author?: string; description?: string; cover?: string; total_chapters?: number; content?: string; created_at: string; updated_at: string }
export interface Chapter { id: number; novel_id: number; number: number; name: string; content?: string; status?: TaskStatusEnum; workflow_status?: number; created_at: string; updated_at: string }
export interface Asset { id: number; novel_id: number; asset_type: AssetTypeEnum; canonical_name: string; aliases?: string[]; description?: string; base_traits?: string; main_image?: string; angle_image_1?: string; angle_image_2?: string; image_source?: number; metadata?: Record<string, unknown>; is_global?: boolean; source_chapters?: number[]; last_updated_chapter?: number; created_at: string; updated_at: string }
export interface Scene { id: number; chapter_id?: number; sequence: number; description?: string; prompt?: string; prompt_params?: Record<string, unknown>; metadata?: Record<string, unknown>; duration?: number; status?: TaskStatusEnum; asset_ids?: number[]; assets?: Asset[]; created_at: string; updated_at: string }
export interface Video { id: number; scene_id: number; model_type: number; url?: string; external_task_id?: string; status: TaskStatusEnum; progress?: number; metadata?: Record<string, unknown>; created_at: string; updated_at: string }
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
export interface AiModelConfig { id: number; task_type: number; task_types?: number[]; name: string; base_url?: string; api_key?: string; model?: string; is_active: boolean; concurrency: number; supports_json_output: boolean; created_at: string; updated_at: string }
export interface AudioReference { id: number; nickname: string; gender: string; audio_url: string; avatar_url: string; asset_id: string; is_active: boolean; created_at: string; updated_at: string }
export interface DigitalHuman { id: number; country: string; age: number; gender: string; occupation: string; asset_id: string; image_url: string; is_active: boolean; created_at: string; updated_at: string }
export interface EnumItem { value: number; label: string }
export interface AllEnums { [key: string]: EnumItem[] }
export interface PaginationResponse<T> { code: number; message: string; data: { items: T[]; pagination: { total: number; page: number; page_size: number; pages: number } } }
export interface SingleResponse<T> { code: number; message: string; data: T }
