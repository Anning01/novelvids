import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { agentApi, runSubscription } from './api'
import { useCreationAgentStore } from './store'
import type { AgentRun } from './types'
import { reactive } from 'vue'

vi.mock('./api', () => ({
  agentApi: { capabilities: vi.fn(), conversations: vi.fn(), create: vi.fn(), history: vi.fn(),
    submit: vi.fn(), snapshot: vi.fn(), stop: vi.fn(), undo: vi.fn() },
  runSubscription: vi.fn(),
}))

const run: AgentRun = { task_id: 'run-1', conversation_id: 1, status: 3, content: '完成', error_message: null, changes: [], usage: {}, event_count: 2 }
const input = { message: '柔和一些', chapter_id: 3, model_config_id: 2, targets: [{ kind: 'scene' as const, id: 9 }] }
const conversation = { id: 1, novel_id: 7, active_task_id: null, created_at: '', updated_at: '' }

beforeEach(() => {
  vi.resetAllMocks()
  setActivePinia(createPinia())
  localStorage.clear()
  vi.mocked(agentApi.capabilities).mockResolvedValue({ code: 0, message: '', data: { enabled: true, can_write: true, max_targets: 8, models: [] } })
  vi.mocked(agentApi.conversations).mockResolvedValue({ code: 0, message: '', data: [conversation] })
  vi.mocked(agentApi.history).mockResolvedValue({ code: 0, message: '', data: { items: [], next_before: null } })
  vi.mocked(agentApi.snapshot).mockResolvedValue({ code: 0, message: '', data: run })
  vi.mocked(runSubscription).mockResolvedValue({ runAgent: vi.fn().mockResolvedValue({}), abortRun: vi.fn() } as unknown as Awaited<ReturnType<typeof runSubscription>>)
})

describe('creation assistant store', () => {
  it('updates the original result card when conversational undo returns its receipt', async () => {
    const store = useCreationAgentStore()
    await store.open(7)
    const change = { id: 16, task_id: 'old-run', changes: [], reverted_at: null, created_at: '' }
    store.messages = [{ id: 1, role: 'assistant', task_id: 'old-run', content: '已移除', status: 3,
      changes: [change], usage: {}, created_at: '' }]
    const restored = { ...change, reverted_at: '2026-09-10T12:00:00Z' }
    vi.mocked(agentApi.snapshot).mockResolvedValue({ code: 0, message: '', data: { ...run, changes: [restored] } })
    await store.follow(run.task_id)
    expect(store.messages[0]?.changes[0]?.reverted_at).toBe(restored.reverted_at)
    expect(store.latestChanges).toEqual([restored])
  })

  it('keeps an accepted run visible when loading message history fails', async () => {
    const store = useCreationAgentStore()
    await store.open(7)
    vi.mocked(agentApi.submit).mockResolvedValue({ code: 0, message: '', data: { ...run, status: 2 } })
    vi.mocked(agentApi.history).mockRejectedValue(new Error('历史连接中断'))
    vi.mocked(runSubscription).mockRejectedValue(new Error('流连接中断'))
    expect(await store.send(input)).toBe(true)
    expect(store.currentRun?.task_id).toBe('run-1')
    expect(store.busy).toBe(true)
    expect(store.messages.find(message => message.role === 'user')?.content).toBe(input.message)
    expect(await store.send(input)).toBe(false)
    expect(agentApi.submit).toHaveBeenCalledOnce()
    expect(store.error).toContain('重新连接')
  })

  it('restores the latest failed run and its saved changes after reopening', async () => {
    const change = { id: 13, task_id: 'run-1', changes: [], reverted_at: null, created_at: '' }
    vi.mocked(agentApi.history).mockResolvedValue({ code: 0, message: '', data: { items: [
      { id: 2, role: 'assistant', content: '', task_id: 'run-1', status: 4, changes: [change], usage: {}, created_at: '' },
    ], next_before: null } })
    vi.mocked(agentApi.snapshot).mockResolvedValue({ code: 0, message: '', data: { ...run, status: 4,
      changes: [change], error_message: '后续请求失败' } })
    const store = useCreationAgentStore()
    await store.open(7)
    expect(store.statusText).toContain('运行未完成')
    expect(store.error).toBe('后续请求失败')
    expect(store.messages[0]?.changes).toEqual([change])
    expect(runSubscription).not.toHaveBeenCalled()
  })

  it('clears the previous run status when switching to an empty conversation', async () => {
    const store = useCreationAgentStore()
    await store.open(7)
    store.statusText = '修改已保存'
    store.error = '之前的错误'
    await store.selectConversation(2)
    expect(store.statusText).toBe('')
    expect(store.error).toBe('')
    expect(store.currentRun).toBeNull()
  })

  it('clears a transient connection error after a successful terminal snapshot', async () => {
    const store = useCreationAgentStore()
    await store.open(7)
    store.error = '连接暂时中断'
    await store.follow('run-1')
    expect(store.statusText).toBe('回复已完成')
    expect(store.error).toBe('')
  })

  it('freezes scope and reuses request id after an uncertain submission', async () => {
    const store = useCreationAgentStore()
    await store.open(7)
    vi.mocked(agentApi.submit).mockRejectedValueOnce(new Error('网络中断')).mockResolvedValueOnce({ code: 0, message: '', data: run })
    expect(await store.send(input)).toBe(false)
    expect(await store.send(input)).toBe(true)
    const calls = vi.mocked(agentApi.submit).mock.calls
    expect(calls[0]?.[1].request_id).toBe(calls[1]?.[1].request_id)
    expect(calls[1]?.[1].targets).toEqual([{ kind: 'scene', id: 9 }])
  })

  it('does not confuse disconnection with server cancellation', async () => {
    const store = useCreationAgentStore()
    await store.open(7)
    store.currentRun = { ...run, status: 2 }
    store.disconnect()
    expect(store.busy).toBe(true)
    expect(agentApi.stop).not.toHaveBeenCalled()
    vi.mocked(agentApi.stop).mockResolvedValue({ code: 0, message: '', data: { ...run, status: 5 } })
    await store.stop()
    expect(store.busy).toBe(false)
    expect(store.statusText).toContain('已停止')
  })

  it('reconstructs a fresh AG-UI client from persisted lifecycle events', async () => {
    const store = useCreationAgentStore()
    await store.open(7)
    store.currentRun = { ...run, status: 2, event_count: 7 }
    await store.follow('run-1')
    expect(runSubscription).toHaveBeenCalledWith(1, 'run-1')
  })

  it('clears private messages when project or identity changes', async () => {
    const store = useCreationAgentStore()
    await store.open(7)
    store.messages = [{ id: 1, role: 'user', content: '私有信息', task_id: 'run', status: 3, changes: [], usage: {}, created_at: '' }]
    vi.mocked(agentApi.conversations).mockResolvedValue({ code: 0, message: '', data: [] })
    await store.open(8)
    expect(store.messages).toEqual([])
    expect(store.conversationId).toBeNull()
  })

  it('surfaces a failed private history restore', async () => {
    const store = useCreationAgentStore()
    vi.mocked(agentApi.history).mockRejectedValue(new Error('历史暂时不可用'))
    await store.open(7)
    expect(store.error).toContain('历史暂时不可用')
    expect(store.messages).toEqual([])
  })

  it('keeps a conflicting undo unchanged and propagates the server error', async () => {
    const store = useCreationAgentStore()
    await store.open(7)
    const change = { id: 2, task_id: 'run', changes: [], reverted_at: null, created_at: '' }
    store.messages = [{ id: 1, role: 'assistant', content: '完成', task_id: 'run', status: 3, changes: [change], usage: {}, created_at: '' }]
    vi.mocked(agentApi.undo).mockRejectedValue(new Error('已有后续修改'))
    await expect(store.undo(2)).rejects.toThrow('已有后续修改')
    expect(store.messages[0]?.changes[0]?.reverted_at).toBeNull()
    expect(store.changesRevision).toBe(0)
  })

  it('copies reactive target selection before an in-flight request', async () => {
    const store = useCreationAgentStore()
    await store.open(7)
    let resolve!: (value: Awaited<ReturnType<typeof agentApi.submit>>) => void
    vi.mocked(agentApi.submit).mockReturnValue(new Promise(done => { resolve = done }))
    const selection = reactive({ ...input, targets: [{ kind: 'scene' as const, id: 9 }] })
    const sending = store.send(selection)
    selection.targets[0]!.id = 10
    expect(vi.mocked(agentApi.submit).mock.calls[0]?.[1].targets[0]?.id).toBe(9)
    resolve({ code: 0, message: '', data: run })
    await sending
  })
})
