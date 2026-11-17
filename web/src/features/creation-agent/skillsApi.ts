import { API_BASE, authHeaders, request } from '@/api'
import { tr } from '@/i18n'
import type { SingleResponse } from '@/types'

export type TextTask = 'story' | 'screenplay' | 'assets' | 'storyboard'
export interface SkillReference { name: string; content: string }
export interface CreativeSkillInput {
  task: TextTask
  name: string
  description: string
  instructions: string
  references: SkillReference[]
  is_active: boolean
}
export interface CreativeSkill extends CreativeSkillInput {
  id: number
  builtin: boolean
  version?: number
}
export interface SkillTrialInput {
  skill: CreativeSkillInput
  model_config_id: number
  input: string
  thinking: string | null
  reasoning_effort: string | null
}
export type SkillTrialEvent = { type: 'status' | 'output' | 'thinking' | 'error' | 'done'; delta?: string; message?: string; status?: string; usage?: { input_tokens?: number; output_tokens?: number } }

export async function runSkillTrial(body: SkillTrialInput, signal: AbortSignal, onEvent: (event: SkillTrialEvent) => void) {
  const response = await fetch(`${API_BASE}/skills/trial`, { method: 'POST', signal,
    headers: { ...authHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new Error(typeof payload?.detail === 'string' ? payload.detail : tr('试运行失败，请重试'))
  }
  if (!response.body) throw new Error(tr('无法读取模型输出，请重试'))
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let terminal = false
  const consume = () => {
    let end: number
    while ((end = buffer.indexOf('\n\n')) >= 0) {
      const frame = buffer.slice(0, end)
      buffer = buffer.slice(end + 2)
      const data = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
      if (!data) continue
      const event = JSON.parse(data) as SkillTrialEvent
      terminal ||= event.type === 'done' || event.type === 'error'
      onEvent(event)
    }
  }
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      consume()
    }
    buffer += decoder.decode()
    consume()
    if (!terminal) throw new Error(tr('连接中断，请重新发送'))
  } finally { await reader.cancel().catch(() => undefined); reader.releaseLock() }
}
export const skillsApi = {
  models: () => request<SingleResponse<{ id: number; name: string; model: string }[]>>('/skills/models'),
  list: (task: TextTask) => request<SingleResponse<{ items: CreativeSkill[]; default_skill_id: number }>>(`/skills?task=${task}`),
  create: (body: CreativeSkillInput) => request<SingleResponse<CreativeSkill>>('/skills', { method: 'POST', body: JSON.stringify(body) }),
  update: (id: number, body: CreativeSkillInput, version: number) => request<SingleResponse<CreativeSkill>>(`/skills/${id}`, {
    method: 'PUT', body: JSON.stringify({ ...body, expected_version: version }),
  }),
  setDefault: (task: TextTask, id: number) => request<SingleResponse<null>>(`/skills/default/${task}`, {
    method: 'PUT', body: JSON.stringify({ skill_id: id }),
  }),
}
