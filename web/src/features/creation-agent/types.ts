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

export interface AgentMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  task_id: string
  status: number
  changes: AgentChange[]
  usage: Record<string, unknown>
  created_at: string
}

export interface AgentRun {
  task_id: string
  conversation_id: number
  status: number
  content: string
  error_message: string | null
  changes: AgentChange[]
  usage: Record<string, unknown>
  event_count: number
}

export interface AgentCapabilities {
  enabled: boolean
  can_write: boolean
  max_targets: number
  models: { id: number; name: string; model: string }[]
}

export interface AgentRunInput {
  request_id: string
  message: string
  chapter_id: number | null
  model_config_id: number | null
  targets: AgentTarget[]
}

export interface AgentConfiguration {
  enabled: boolean
  request_limit: number
  tool_calls_limit: number
  max_targets: number
  timeout_seconds: number
  max_context_characters: number
  history_runs: number
  max_output_tokens: number
  total_tokens_limit: number
}
