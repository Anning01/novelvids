import type { VideoGenerationOptions } from '@/types'

export interface AgentTarget {
  kind: 'asset' | 'variant' | 'scene'
  id: number
}

export interface PromptTargetStatus extends AgentTarget {
  pending_constraints: { id: number; content: string }[]
}

export interface AgentChangeItem {
  kind: AgentTarget['kind']
  target_id: number
  asset_id?: number | null
  target_label?: string | null
  before: Record<string, unknown>
  after: Record<string, unknown>
  after_version: string
  operation?: 'create' | 'update' | 'delete'
  chapter_id?: number | null
  recovery?: Record<string, unknown>
}

export interface AgentQueryItem {
  kind: AgentTarget['kind'] | 'chapter'
  id: number
  name: string
  asset_id?: number | null
  chapter_id?: number | null
}

export interface AgentQueryResult {
  items: AgentQueryItem[]
  total: number
  has_more: boolean
}

export interface AgentChange {
  id: number
  task_id: string
  changes: AgentChangeItem[]
  reverted_at: string | null
  created_at: string
}

export interface AgentConversation {
  id: number
  novel_id: number
  active_task_id: string | null
  created_at: string
  updated_at: string
  title?: string
}

export interface ProductionReceipt { task_id: string; operation: string; status: number; stage?: string | null; error?: string | null }

export interface AgentMessage {
  production?: ProductionReceipt[]
  id: number
  role: 'user' | 'assistant'
  content: string
  task_id: string
  status: number
  changes: AgentChange[]
  usage: Record<string, unknown>
  created_at: string
  query_results?: AgentQueryResult[]
}

export interface AgentRun {
  production?: ProductionReceipt[]
  task_id: string
  conversation_id: number
  status: number
  content: string
  error_message: string | null
  changes: AgentChange[]
  usage: Record<string, unknown>
  event_count: number
  query_results?: AgentQueryResult[]
}

export interface AgentCapabilities {
  enabled: boolean
  can_write: boolean
  max_targets: number
  models: { id: number; name: string; model: string }[]
}

export interface ProductionIntent {
  operation: 'story' | 'assets' | 'image' | 'storyboard' | 'video' | 'compose'
  target_id: number
  request_id: string
  media_model_config_id?: number | null
  variant_id?: number | null
  video_options?: VideoGenerationOptions | null
  replace_existing?: boolean
}

export interface AgentRunInput {
  production_intents?: ProductionIntent[]
  request_id: string
  message: string
  chapter_id: number | null
  model_config_id: number | null
  targets: AgentTarget[]
  write_scope?: 'selected' | 'chapter' | 'project' | 'read_only'
}

export interface AgentConfiguration {
  production_concurrency?: number
  enabled: boolean
  request_limit: number
  tool_calls_limit: number
  max_targets: number
  timeout_seconds: number
  max_context_characters: number
  working_input_tokens?: number
  compaction_trigger_ratio?: number
  compaction_target_ratio?: number
  summary_output_tokens?: number
  summary_timeout_seconds?: number
  context_page_characters?: number
  history_runs: number
  max_output_tokens: number
  total_tokens_limit: number
}
