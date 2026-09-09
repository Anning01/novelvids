import type { HttpAgent } from '@ag-ui/client'
import { API_BASE, authHeaders, clearAuthToken, redirectToLogin, request } from '@/api'
import type { SingleResponse } from '@/types'
import type { AgentCapabilities, AgentChange, AgentConversation, AgentMessage, AgentRun, AgentRunInput, AgentConfiguration, AgentTarget, PromptTargetStatus } from './types'

const base = '/creation-agent'
export const agentApi = {
  promptStatus: (novelId: number, chapterId: number, targets: AgentTarget[]) => request<SingleResponse<PromptTargetStatus[]>>(`${base}/prompt-status?novel_id=${novelId}`, {
    method: 'POST', body: JSON.stringify({ chapter_id: chapterId || null, targets }),
  }),
  configuration: () => request<SingleResponse<AgentConfiguration>>(`${base}/configuration`),
  updateConfiguration: (configuration: AgentConfiguration) => request<SingleResponse<AgentConfiguration>>(`${base}/configuration`, {
    method: 'PUT', body: JSON.stringify(configuration),
  }),
  capabilities: (novelId: number) => request<SingleResponse<AgentCapabilities>>(`${base}/capabilities?novel_id=${novelId}`),
  conversations: (novelId: number) => request<SingleResponse<AgentConversation[]>>(`${base}/conversations?novel_id=${novelId}`),
  create: (novelId: number) => request<SingleResponse<AgentConversation>>(`${base}/conversations`, {
    method: 'POST', body: JSON.stringify({ novel_id: novelId }),
  }),
  history: (id: number, before?: number) => request<SingleResponse<{ items: AgentMessage[]; next_before: number | null }>>(
    `${base}/conversations/${id}/messages${before ? `?before=${before}` : ''}`,
  ),
  submit: (id: number, input: AgentRunInput) => request<SingleResponse<AgentRun>>(`${base}/conversations/${id}/runs`, {
    method: 'POST', body: JSON.stringify(input),
  }),
  snapshot: (taskId: string) => request<SingleResponse<AgentRun>>(`${base}/runs/${taskId}`),
  stop: (taskId: string) => request<SingleResponse<AgentRun>>(`${base}/runs/${taskId}/stop`, { method: 'POST' }),
  undo: (changeId: number) => request<SingleResponse<AgentChange>>(`${base}/changes/${changeId}/undo`, { method: 'POST' }),
}

export async function runSubscription(conversationId: number, taskId: string, after = 0): Promise<HttpAgent> {
  const { HttpAgent } = await import('@ag-ui/client')
  return new HttpAgent({
    url: `${API_BASE}${base}/runs/${taskId}/events?after=${after}`, threadId: String(conversationId),
    headers: authHeaders(), initialMessages: [], initialState: {},
    fetch: async (url, init) => {
      const response = await fetch(url, init)
      if (!response.headers.get('content-type')?.includes('text/event-stream')) {
        const body = await response.json() as { code?: number; message?: string }
        if (body.code === 401) { clearAuthToken(); redirectToLogin() }
        throw new Error(body.message || '无法连接创作助手')
      }
      return response
    },
  })
}
