import { API_BASE, authHeaders, request } from '@/api'
import { tr } from '@/i18n'
import type { SingleResponse } from '@/types'
import type { EpisodePacing } from '@/types'

export type TextTask = 'story' | 'screenplay' | 'assets' | 'storyboard'
export interface SkillReference { name: string; content: string }
export interface SkillFile { path: string; content: string; encoding: 'utf-8' | 'base64'; executable?: boolean }
export interface SkillPackageLimits { max_files: number; max_file_bytes: number; max_package_bytes: number; max_archive_bytes: number }
export interface CreativeSkillInput {
  task: TextTask
  name: string
  description: string
  instructions: string
  references: SkillReference[]
  files?: SkillFile[]
  is_active: boolean
}
export interface CreativeSkill extends CreativeSkillInput {
  id: number
  builtin: boolean
  version?: number
  is_summary?: boolean
  limits?: SkillPackageLimits
}
export interface SkillPackageDraft extends CreativeSkillInput { files: SkillFile[]; limits: SkillPackageLimits }
export function skillRequestBody(body: CreativeSkillInput) {
  const { instructions, references, files } = body
  const metadata = { task: body.task, name: body.name, description: body.description, is_active: body.is_active }
  return files ? { ...metadata, files: files.map(file => ({ path: file.path, content: file.content, encoding: file.encoding, executable: file.executable ?? false })) }
    : { ...metadata, instructions, references }
}
export interface SkillTrialInput {
  skill: CreativeSkillInput
  model_config_id: number
  input: string
  episode_pacing?: EpisodePacing
  thinking: string | null
  reasoning_effort: string | null
}
export type SkillTrialEvent = { type: 'status' | 'output' | 'thinking' | 'error' | 'done'; delta?: string; message?: string; status?: string; usage?: { input_tokens?: number; output_tokens?: number } }

export async function runSkillTrial(body: SkillTrialInput, signal: AbortSignal, onEvent: (event: SkillTrialEvent) => void) {
  const response = await fetch(`${API_BASE}/skills/trial`, { method: 'POST', signal,
    headers: { ...authHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify({ ...body, skill: skillRequestBody(body.skill) }) })
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
  setActive: (id: number, isActive: boolean, version: number) => request<SingleResponse<CreativeSkill>>(`/skills/${id}/status`, {
    method: 'PATCH', body: JSON.stringify({ is_active: isActive, expected_version: version }),
  }),
  packageFormat: (task: TextTask) => request<SingleResponse<{ files: SkillFile[]; limits: SkillPackageLimits }>>(`/skills/package-format?task=${task}`),
  detail: (id: number, task: TextTask) => request<SingleResponse<CreativeSkill>>(`/skills/${id}?task=${task}`),
  importArchive: (task: TextTask, file: File) => {
    const body = new FormData()
    body.append('task', task); body.append('file', file)
    return request<SingleResponse<SkillPackageDraft>>('/skills/import', { method: 'POST', body })
  },
  exportArchive: async (body: CreativeSkillInput) => {
    const response = await fetch(`${API_BASE}/skills/export`, { method: 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify(skillRequestBody(body)) })
    if (!response.ok) {
      const payload = await response.json().catch(() => null)
      throw new Error(typeof payload?.detail === 'string' ? payload.detail : tr('技能包导出失败，请重试'))
    }
    return response.blob()
  },
  models: () => request<SingleResponse<{ id: number; name: string; model: string }[]>>('/skills/models'),
  list: (task: TextTask) => request<SingleResponse<{ items: CreativeSkill[]; default_skill_id: number }>>(`/skills?task=${task}`),
  create: (body: CreativeSkillInput) => request<SingleResponse<CreativeSkill>>('/skills', { method: 'POST', body: JSON.stringify(skillRequestBody(body)) }),
  update: (id: number, body: CreativeSkillInput, version: number) => request<SingleResponse<CreativeSkill>>(`/skills/${id}`, {
    method: 'PUT', body: JSON.stringify({ ...skillRequestBody(body), expected_version: version }),
  }),
  setDefault: (task: TextTask, id: number) => request<SingleResponse<null>>(`/skills/default/${task}`, {
    method: 'PUT', body: JSON.stringify({ skill_id: id }),
  }),
}
