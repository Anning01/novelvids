import { request } from '@/api'
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
