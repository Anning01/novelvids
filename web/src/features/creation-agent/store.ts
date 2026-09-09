import { defineStore } from 'pinia'
import { computed, markRaw, ref } from 'vue'
import { getActiveTeamId, getAuthToken } from '@/api'
import { agentApi, runSubscription } from './api'
import type { HttpAgent } from '@ag-ui/client'
import type { AgentCapabilities, AgentChange, AgentConversation, AgentMessage, AgentRun, AgentRunInput } from './types'

const activeStatuses = new Set([1, 2, 6])
export const isAgentRunning = (status: number) => activeStatuses.has(status)

export const useCreationAgentStore = defineStore('creation-agent', () => {
  const projectId = ref(0)
  const conversations = ref<AgentConversation[]>([])
  const conversationId = ref<number | null>(null)
  const messages = ref<AgentMessage[]>([])
  const capabilities = ref<AgentCapabilities | null>(null)
  const currentRun = ref<AgentRun | null>(null)
  const loading = ref(false)
  const submitting = ref(false)
  const streamConnected = ref(false)
  const statusText = ref('')
  const error = ref('')
  const nextBefore = ref<number | null>(null)
  const changesRevision = ref(0)
  const latestChanges = ref<AgentChange[]>([])
  const busy = computed(() => submitting.value || Boolean(currentRun.value && isAgentRunning(currentRun.value.status)))
  let subscription: HttpAgent | null = null
  let epoch = 0
  let subscriptionAttempt = 0
  let identity = ''
  let pendingRequest: { conversationId: number; input: AgentRunInput } | null = null
  const observed = new Map<number, string | null>()

  function disconnect() {
    subscriptionAttempt += 1
    subscription?.abortRun()
    subscription = null
    streamConnected.value = false
  }

  function reportChanges(changes: AgentChange[]) {
    const changed = changes.filter(change => observed.has(change.id)
      ? observed.get(change.id) !== change.reverted_at : true)
    changes.forEach(change => observed.set(change.id, change.reverted_at))
    if (changed.length) { latestChanges.value = changed; changesRevision.value += 1 }
  }

  function applySnapshot(run: AgentRun) {
    currentRun.value = run
    const message = messages.value.find(item => item.task_id === run.task_id && item.role === 'assistant')
    if (message) Object.assign(message, { content: run.content, changes: run.changes, usage: run.usage, status: run.status })
    reportChanges(run.changes)
    if (!isAgentRunning(run.status)) {
      statusText.value = run.status === 3 ? (run.changes.length ? '修改已保存' : '回复已完成')
        : run.status === 5 ? '已停止，已保存的修改仍保留' : '运行未完成，已保存的修改仍可查看'
      error.value = run.error_message || ''
    }
  }

  async function history(before?: number) {
    if (!conversationId.value) return
    const id = conversationId.value
    const revision = epoch
    const response = await agentApi.history(id, before)
    if (revision !== epoch || id !== conversationId.value) return
    messages.value = before ? [...response.data.items, ...messages.value] : response.data.items
    nextBefore.value = response.data.next_before
    response.data.items.flatMap(message => message.changes).forEach(change => observed.set(change.id, change.reverted_at))
  }

  async function follow(taskId: string) {
    if (!conversationId.value) return
    disconnect()
    const revision = epoch
    const id = conversationId.value
    const attempt = subscriptionAttempt
    // A fresh AG-UI client needs RUN_STARTED/message-start events to reconstruct its state.
    // Replaying stored events is read-only and does not re-execute the model or its tools.
    const handle = markRaw(await runSubscription(id, taskId))
    if (revision !== epoch || attempt !== subscriptionAttempt) { handle.abortRun(); return }
    subscription = handle
    streamConnected.value = true
    try {
      await handle.runAgent({ runId: taskId }, {
        onTextMessageContentEvent({ textMessageBuffer }) {
          if (revision !== epoch || subscription !== handle) return
          const message = messages.value.find(item => item.task_id === taskId && item.role === 'assistant')
          if (message) message.content = textMessageBuffer
        },
        onToolCallStartEvent({ event }) {
          if (revision !== epoch || subscription !== handle) return
          statusText.value = event.toolCallName === 'get_creation_context' ? '正在读取当前设定' : '正在调整提示词'
        },
        async onToolCallResultEvent() {
          const result = await agentApi.snapshot(taskId)
          if (revision === epoch && subscription === handle) applySnapshot(result.data)
        },
      })
    } catch (caught) {
      if (revision === epoch && subscription === handle) error.value = caught instanceof Error ? caught.message : '连接中断，可重新连接查看结果'
    } finally {
      if (revision === epoch && subscription === handle) {
        streamConnected.value = false
        subscription = null
        try {
          const response = await agentApi.snapshot(taskId)
          if (revision === epoch) applySnapshot(response.data)
        } catch { if (revision === epoch) error.value = '连接中断，请重新连接核对实际结果' }
      }
    }
  }

  async function selectConversation(id: number) {
    disconnect()
    epoch += 1
    conversationId.value = id
    currentRun.value = null
    pendingRequest = null
    messages.value = []
    error.value = ''
    statusText.value = ''
    observed.clear()
    const revision = epoch
    try {
      await history()
      if (revision !== epoch) return
      const latestTaskId = conversations.value.find(item => item.id === id)?.active_task_id
        ?? [...messages.value].reverse().find(message => message.role === 'assistant')?.task_id
      if (latestTaskId) {
        const response = await agentApi.snapshot(latestTaskId)
        if (revision !== epoch) return
        applySnapshot(response.data)
        if (isAgentRunning(response.data.status)) void follow(latestTaskId)
      }
    } catch (caught) {
      if (revision === epoch) error.value = caught instanceof Error ? caught.message : '无法恢复当前对话'
    }
  }

  async function open(novelId: number) {
    const nextIdentity = `${getAuthToken() || ''}:${getActiveTeamId() || ''}`
    disconnect()
    epoch += 1
    const revision = epoch
    if (identity !== nextIdentity || projectId.value !== novelId) {
      conversationId.value = null; currentRun.value = null; messages.value = []; pendingRequest = null
      statusText.value = ''
      observed.clear(); latestChanges.value = []
    }
    identity = nextIdentity
    projectId.value = novelId
    loading.value = true
    error.value = ''
    try {
      const [available, listed] = await Promise.all([agentApi.capabilities(novelId), agentApi.conversations(novelId)])
      if (revision !== epoch) return
      capabilities.value = available.data
      conversations.value = listed.data
      const selected = listed.data.find(item => item.id === conversationId.value) ?? listed.data[0]
      if (selected) await selectConversation(selected.id)
    } catch (caught) {
      if (revision === epoch) error.value = caught instanceof Error ? caught.message : '加载助手失败'
    } finally { if (projectId.value === novelId) loading.value = false }
  }

  async function newConversation() {
    if (busy.value) return
    const revision = epoch
    const created = await agentApi.create(projectId.value)
    if (revision !== epoch) return
    conversations.value.unshift(created.data)
    await selectConversation(created.data.id)
  }

  async function send(input: Omit<AgentRunInput, 'request_id'>) {
    if (busy.value) return false
    submitting.value = true
    error.value = ''
    const revision = epoch
    const frozenInput = { ...input, targets: input.targets.map(target => ({ kind: target.kind, id: target.id })) }
    try {
      if (!conversationId.value) {
        const created = await agentApi.create(projectId.value)
        if (revision !== epoch) return false
        conversations.value.unshift(created.data)
        conversationId.value = created.data.id
      }
      const id = conversationId.value
      const matching = pendingRequest?.conversationId === id
        && JSON.stringify({ ...pendingRequest.input, request_id: undefined }) === JSON.stringify(frozenInput)
      const body: AgentRunInput = matching && pendingRequest ? pendingRequest.input : { ...frozenInput, request_id: crypto.randomUUID() }
      pendingRequest = { conversationId: id, input: body }
      const response = await agentApi.submit(id, body)
      if (revision !== epoch) return false
      pendingRequest = null
      await history()
      if (revision !== epoch) return false
      applySnapshot(response.data)
      const conversation = conversations.value.find(item => item.id === id)
      if (conversation) conversation.active_task_id = response.data.task_id
      statusText.value = '正在处理你的创作要求'
      void follow(response.data.task_id)
      return true
    } catch (caught) {
      if (revision === epoch) error.value = caught instanceof Error ? caught.message : '提交失败，请重试以核对结果'
      return false
    } finally { submitting.value = false }
  }

  async function stop() {
    if (!currentRun.value) return
    const response = await agentApi.stop(currentRun.value.task_id)
    disconnect()
    applySnapshot(response.data)
  }

  async function undo(changeId: number) {
    const response = await agentApi.undo(changeId)
    messages.value.forEach(message => {
      message.changes = message.changes.map(change => change.id === changeId ? response.data : change)
    })
    reportChanges([response.data])
  }

  return { projectId, conversations, conversationId, messages, capabilities, currentRun, loading, submitting,
    streamConnected, busy, error, statusText, nextBefore, changesRevision, latestChanges,
    open, history, send, stop, undo, newConversation, selectConversation, follow, disconnect }
})
