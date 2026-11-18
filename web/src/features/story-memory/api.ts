import { request } from '@/api'
import type { AiTask, SingleResponse } from '@/types'
import type { MemoryCandidate, MemoryCommit, MemoryContext, MemoryDetail, MemoryStatus } from './types'

const base = (id: number) => `/novel/${id}/story-memory`
export const storyMemoryApi = {
  status: (id: number, signal?: AbortSignal) => request<SingleResponse<MemoryStatus>>(`${base(id)}/status`, { signal }),
  context: (id: number, chapterId: number | null, signal?: AbortSignal) => request<SingleResponse<MemoryContext>>(`${base(id)}/context${chapterId ? `?chapter_id=${chapterId}` : ''}`, { signal }),
  history: (id: number, before?: number, signal?: AbortSignal) => request<SingleResponse<MemoryCommit[]>>(`${base(id)}/commits?limit=30${before ? `&before_id=${before}` : ''}`, { signal }),
  detail: (id: number, commitId: number, signal?: AbortSignal) => request<SingleResponse<MemoryDetail>>(`${base(id)}/commits/${commitId}`, { signal }),
  activity: (id: number, signal?: AbortSignal) => request<SingleResponse<AiTask | null>>(`${base(id)}/activity`, { signal }),
  analyze: (id: number, chapterId: number | null, modelId: number, skillId?: number) => request<SingleResponse<AiTask>>(`${base(id)}/analyze`, {
    method: 'POST', body: JSON.stringify({ request_id: crypto.randomUUID(), chapter_id: chapterId, assistant_model_config_id: modelId, skill_id: skillId }),
  }),
  recheck: (id: number, modelId: number, skillId?: number) => request<SingleResponse<AiTask>>(`${base(id)}/recheck`, {
    method: 'POST', body: JSON.stringify({ request_id: crypto.randomUUID(), assistant_model_config_id: modelId, skill_id: skillId }),
  }),
  update: (id: number, commitId: number, candidate: MemoryCandidate, revision: number) => request<SingleResponse<MemoryDetail>>(`${base(id)}/commits/${commitId}/candidate`, {
    method: 'PUT', body: JSON.stringify({ candidate, expected_revision: revision }),
  }),
  review: (id: number, commitId: number, revision: number, modelId: number) => request<SingleResponse<AiTask>>(`${base(id)}/commits/${commitId}/review`, {
    method: 'POST', body: JSON.stringify({ expected_revision: revision, assistant_model_config_id: modelId }),
  }),
  repair: (id: number, commitId: number, revision: number, hash: string, modelId?: number) => request<SingleResponse<AiTask>>(`${base(id)}/commits/${commitId}/repair`, {
    method: 'POST', body: JSON.stringify({ expected_revision: revision, expected_package_hash: hash, assistant_model_config_id: modelId }),
  }),
  decide: (id: number, commitId: number, hash: string, decision: 'accept' | 'reject', note: string) => request<SingleResponse<MemoryDetail>>(`${base(id)}/commits/${commitId}/decision`, {
    method: 'POST', body: JSON.stringify({ expected_package_hash: hash, decision, note }),
  }),
}
