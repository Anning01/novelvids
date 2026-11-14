import { generationRequest, finishGenerationRequest } from '@/shared/generationRequests'
import { applyActivityEvent, mergeActivity, type ActivityEvent } from './activity'
import { creationAgentToolProgressLabel } from './toolPresentation'

import { tr } from '@/i18n'
import { defineStore } from 'pinia'
import { computed, markRaw, ref } from 'vue'
import { getActiveTeamId, getAuthToken } from '@/api'
import { agentApi, runSubscription } from './api'
import type { HttpAgent } from '@ag-ui/client'
import type { AgentActivityStep, AgentCapabilities, AgentChange, AgentConversation, AgentMessage, AgentRun, AgentRunInput } from './types'

const activeStatuses = new Set([1, 2, 6])
export const isAgentRunning = (status: number) => activeStatuses.has(status)

export const useCreationAgentStore = defineStore('creation-agent', () => {
  const snapshotRequests = new Map<string, ReturnType<typeof agentApi.snapshot>>()
  function snapshot(taskId: string) {
    const key = `${epoch}:${taskId}`
    const pending = snapshotRequests.get(key)
    if (pending) return pending
    const request = agentApi.snapshot(taskId).finally(() => snapshotRequests.delete(key))
    snapshotRequests.set(key, request)
    return request
  }
  const projectId = ref(0)
  const conversations = ref<AgentConversation[]>([])
  const deletedConversations = ref<AgentConversation[]>([])
  const sessionBusy = ref(false)
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
  const observed = new Map<number, string | null>()

  function disconnect() {
    subscriptionAttempt += 1
    subscription?.abortRun()
    subscription = null
    streamConnected.value = false
  }

  function reportChanges(changes: AgentChange[]) {
    const receipts = new Map(changes.map(change => [change.id, change]))
    messages.value.forEach(message => {
      message.changes = message.changes.map(change => receipts.get(change.id) ?? change)
    })
    const changed = changes.filter(change => observed.has(change.id)
      ? observed.get(change.id) !== change.reverted_at : true)
    changes.forEach(change => observed.set(change.id, change.reverted_at))
    if (changed.length) { latestChanges.value = changed; changesRevision.value += 1 }
  }

  function applySnapshot(run: AgentRun) {
    currentRun.value = run
    const message = messages.value.find(item => item.task_id === run.task_id && item.role === 'assistant')
    if (message) Object.assign(message, {
      recovery: run.recovery,
      activity: streamConnected.value && isAgentRunning(run.status)
        ? mergeActivity(run.activity || [], message.activity || [])
        : run.activity, started_at: run.started_at, finished_at: run.finished_at, content: isAgentRunning(run.status) && !run.content ? message.content : run.content, changes: run.changes, usage: run.usage, status: run.status, query_results: run.query_results || [], production: run.production || [], pending_production: run.pending_production })
    reportChanges(run.changes)
    if (isAgentRunning(run.status)) {
      // A successful snapshot proves the job is alive even if its event stream
      // disconnected. Do not keep a transport error displayed as a task failure.
      error.value = run.error_message || ''
      if (!streamConnected.value) statusText.value = tr('正在处理你的创作要求')
    } else {
      statusText.value = run.status === 3 ? (run.usage.turn_limited ? tr('本轮处理已结束，可以继续对话') : run.changes.length ? tr('修改已保存') : tr('回复已完成'))
        : run.status === 5 ? tr('已停止，已保存的修改仍保留') : tr('运行未完成，已保存的修改仍可查看')
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
    let handle: HttpAgent
    try { handle = markRaw(await runSubscription(id, taskId)) }
    catch {
      if (revision === epoch && attempt === subscriptionAttempt) error.value = tr('连接中断，可重新连接查看结果')
      return
    }
    if (revision !== epoch || attempt !== subscriptionAttempt) { handle.abortRun(); return }
    subscription = handle
    streamConnected.value = true
    const liveActivity: AgentActivityStep[] = []
    try {
      await handle.runAgent({ runId: taskId }, {
        onEvent({ event }) {
          if (revision !== epoch || subscription !== handle) return
          applyActivityEvent(liveActivity, event as ActivityEvent)
          const message = messages.value.find(item => item.task_id === taskId && item.role === 'assistant')
          if (message) message.activity = mergeActivity(message.activity || [], liveActivity)
        },
        onTextMessageContentEvent({ textMessageBuffer }) {
          if (revision !== epoch || subscription !== handle) return
          const message = messages.value.find(item => item.task_id === taskId && item.role === 'assistant')
          if (message) message.content = textMessageBuffer
        },
        onCustomEvent({ event }) {
          if (revision !== epoch || subscription !== handle) return
          if (event.name === 'context_compaction') statusText.value = tr('正在整理上下文')
        },
        onToolCallStartEvent({ event }) {
          if (revision !== epoch || subscription !== handle) return
          statusText.value = creationAgentToolProgressLabel(event.toolCallName)
        },
        async onToolCallResultEvent() {
          const result = await snapshot(taskId)
          if (revision === epoch && subscription === handle) applySnapshot(result.data)
        },
      })
    } catch (caught) {
      if (revision === epoch && subscription === handle) error.value = tr('实时连接中断，正在恢复任务状态')
    } finally {
      if (revision === epoch && subscription === handle) {
        streamConnected.value = false
        subscription = null
        try {
          const response = await snapshot(taskId)
          if (revision === epoch) applySnapshot(response.data)
        } catch { if (revision === epoch) error.value = tr('连接中断，请重新连接') }
      }
    }
  }

  function selectionKey(novelId = projectId.value) {
    return `creation-agent:conversation:${getActiveTeamId() ?? 'personal'}:${novelId}`
  }

  async function selectConversation(id: number | null) {
    const sameConversation = conversationId.value === id
    disconnect()
    epoch += 1
    conversationId.value = id
    if (id !== null) sessionStorage.setItem(selectionKey(), String(id))
    currentRun.value = null
    if (!sameConversation) messages.value = []
    error.value = ''
    statusText.value = ''
    observed.clear()
    nextBefore.value = null
    if (id === null) { loading.value = false; return }
    const revision = epoch
    loading.value = true
    try {
      await history()
      if (revision !== epoch) return
      const latestTaskId = conversations.value.find(item => item.id === id)?.active_task_id
        ?? [...messages.value].reverse().find(message => message.role === 'assistant')?.task_id
      if (latestTaskId) {
        const response = await snapshot(latestTaskId)
        if (revision !== epoch) return
        applySnapshot(response.data)
        if (isAgentRunning(response.data.status)) void follow(latestTaskId)
      }
    } catch (caught) {
      if (revision === epoch) error.value = caught instanceof Error ? caught.message : tr('无法恢复当前对话')
    } finally { if (revision === epoch) loading.value = false }
  }

  async function open(novelId: number) {
    const nextIdentity = `${getAuthToken() || ''}:${getActiveTeamId() || ''}`
    disconnect()
    epoch += 1
    const revision = epoch
    if (identity !== nextIdentity || projectId.value !== novelId) {
      conversationId.value = null; currentRun.value = null; messages.value = []
      capabilities.value = null; conversations.value = []; nextBefore.value = null
      deletedConversations.value = []
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
      const remembered = Number(sessionStorage.getItem(selectionKey(novelId)))
      const selected = listed.data.find(item => item.id === conversationId.value)
        ?? listed.data.find(item => item.id === remembered) ?? listed.data[0]
      await selectConversation(selected?.id ?? null)
    } catch (caught) {
      if (revision === epoch) error.value = caught instanceof Error ? caught.message : tr('加载助手失败')
    } finally { if (revision === epoch) loading.value = false }
  }

  async function refreshConversations() {
    if (!projectId.value || loading.value) return
    const revision = epoch
    const id = projectId.value
    const selectedId = conversationId.value
    const previous = conversations.value.find(item => item.id === selectedId)
    const listed = await agentApi.conversations(id)
    if (revision !== epoch || projectId.value !== id) return
    conversations.value = listed.data
    const selected = listed.data.find(item => item.id === selectedId)
    if (selected && !busy.value && (selected.updated_at !== previous?.updated_at || selected.active_task_id !== previous?.active_task_id)) {
      await selectConversation(selected.id)
    }
  }

  async function newConversation() {
    if (busy.value || sessionBusy.value || loading.value) return
    const revision = epoch
    sessionBusy.value = true
    try {
      const created = await agentApi.create(projectId.value)
      if (revision !== epoch) return
      conversations.value.unshift(created.data)
      await selectConversation(created.data.id)
    } finally { sessionBusy.value = false }
  }

  async function loadDeletedConversations() {
    const revision = epoch
    const response = await agentApi.conversations(projectId.value, true)
    if (revision === epoch) deletedConversations.value = response.data
  }

  async function deleteConversation(id: number) {
    if (busy.value || sessionBusy.value || loading.value) return
    const revision = epoch
    sessionBusy.value = true
    try {
      await agentApi.deleteConversation(id)
      if (revision !== epoch) return
      const removed = conversations.value.find(item => item.id === id)
      conversations.value = conversations.value.filter(item => item.id !== id)
      if (removed) deletedConversations.value = [removed, ...deletedConversations.value.filter(item => item.id !== id)]
      if (id === conversationId.value) await selectConversation(conversations.value[0]?.id ?? null)
    } finally { sessionBusy.value = false }
  }

  async function restoreConversation(id: number) {
    if (busy.value || sessionBusy.value || loading.value) return
    const revision = epoch
    sessionBusy.value = true
    try {
      const response = await agentApi.restoreConversation(id)
      if (revision !== epoch) return
      const previous = deletedConversations.value.find(item => item.id === id)
      conversations.value = [{ ...response.data, title: previous?.title || response.data.title }, ...conversations.value.filter(item => item.id !== id)]
      conversations.value.sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at) || b.id - a.id)
      deletedConversations.value = deletedConversations.value.filter(item => item.id !== id)
    } finally { sessionBusy.value = false }
  }

  async function send(input: Omit<AgentRunInput, 'request_id'> & { request_id?: string }) {
    if (busy.value || sessionBusy.value || loading.value) return false
    submitting.value = true
    error.value = ''
    const revision = epoch
    const { request_id: explicitRequestId, ...content } = input
    // Freeze the JSON wire payload before hashing or other awaits can let the
    // current Vue selection or a confirmed proposal change underneath it.
    const frozenInput: Omit<AgentRunInput, 'request_id'> = JSON.parse(JSON.stringify(content))
    try {
      if (!conversationId.value) {
        const created = await agentApi.resumeOrCreate(projectId.value)
        if (revision !== epoch) return false
        conversations.value.unshift(created.data)
        conversationId.value = created.data.id
        sessionStorage.setItem(selectionKey(), String(created.data.id))
      }
      const id = conversationId.value
      const receipt = await generationRequest(JSON.stringify([getAuthToken(), getActiveTeamId()]),
        `/creation-agent/conversations/${id}/runs`, JSON.stringify(frozenInput))
      const body: AgentRunInput = { ...frozenInput, request_id: explicitRequestId ?? receipt.id }
      const response = await agentApi.submit(id, body)
      finishGenerationRequest(receipt.key)
      if (revision !== epoch) return false
      applySnapshot(response.data)
      // A history read failure cannot turn an accepted (possibly billable) run into a failed submission.
      try { await history() }
      catch {
        if (revision !== epoch) return true
        const localId = -Date.now()
        messages.value.push(
          { id: localId, role: 'user', content: frozenInput.message, task_id: response.data.task_id, status: response.data.status, changes: [], usage: {}, created_at: new Date().toISOString() },
          { id: localId - 1, role: 'assistant', content: response.data.content, task_id: response.data.task_id, status: response.data.status, changes: response.data.changes, usage: response.data.usage, created_at: new Date().toISOString() },
        )
        error.value = tr('要求已提交，对话记录暂时未同步，可重新连接。')
      }
      if (revision !== epoch) return false
      applySnapshot(response.data)
      const conversation = conversations.value.find(item => item.id === id)
      if (conversation) {
        conversation.active_task_id = response.data.task_id
        conversation.updated_at = new Date().toISOString()
        if (!conversation.title || conversation.title === '新会话') conversation.title = frozenInput.message.replace(/\s+/g, ' ').slice(0, 40)
        conversations.value = [conversation, ...conversations.value.filter(item => item.id !== id)]
      }
      if (isAgentRunning(response.data.status)) {
        statusText.value = tr('正在处理你的创作要求')
        void follow(response.data.task_id)
      }
      return true
    } catch (caught) {
      if (revision === epoch) error.value = caught instanceof Error ? caught.message : tr('提交未完成，请重试')
      return false
    } finally { submitting.value = false }
  }

  async function refreshProduction() {
    const revision = epoch
    const runs = [...new Set(messages.value.filter(message => message.role === 'assistant'
      && (isAgentRunning(message.status) || message.production?.some(receipt => isAgentRunning(receipt.status)))).map(message => message.task_id))]
    await Promise.allSettled(runs.map(async taskId => {
      const response = await snapshot(taskId)
      if (revision !== epoch) return
      if (currentRun.value?.task_id === taskId) { applySnapshot(response.data); return }
      const message = messages.value.find(item => item.task_id === taskId && item.role === 'assistant')
      if (message) Object.assign(message, { production: response.data.production || [], usage: response.data.usage,
        activity: streamConnected.value && isAgentRunning(response.data.status)
          ? mergeActivity(response.data.activity || [], message.activity || [])
          : response.data.activity, started_at: response.data.started_at, finished_at: response.data.finished_at })
    }))
  }

  async function stop() {
    if (!currentRun.value) return
    const response = await agentApi.stop(currentRun.value.task_id)
    disconnect()
    applySnapshot(response.data)
  }

  async function resume() {
    if (!currentRun.value || submitting.value || busy.value) return
    const revision = epoch
    const taskId = currentRun.value.task_id
    submitting.value = true
    try {
      const response = await agentApi.resume(taskId)
      if (revision !== epoch) return
      disconnect()
      applySnapshot(response.data)
      if (isAgentRunning(response.data.status)) void follow(taskId)
    } catch (caught) {
      if (revision === epoch) error.value = caught instanceof Error ? caught.message : tr('续跑失败，请稍后检查')
    } finally { submitting.value = false }
  }

  async function undo(changeId: number) {
    const response = await agentApi.undo(changeId)
    reportChanges([response.data])
  }

  return { projectId, conversations, deletedConversations, conversationId, messages, capabilities, currentRun, loading, submitting, sessionBusy,
    streamConnected, busy, error, statusText, nextBefore, changesRevision, latestChanges,
    open, history, send, stop, resume, undo, refreshProduction, newConversation, selectConversation, follow, disconnect,
    deleteConversation, restoreConversation, loadDeletedConversations, refreshConversations }
})
