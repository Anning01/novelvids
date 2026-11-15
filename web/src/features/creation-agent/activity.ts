import type { AgentActivityStep } from './types'

export interface ActivityEvent {
  type: string
  timestamp?: number
  toolCallId?: string
  toolCallName?: string
  delta?: string
  name?: string
  value?: AgentActivityStep & { detail_delta?: string; detail_offset?: number }
}

/** Build the visible timeline from the same events used for stream replay. */
export function applyActivityEvent(steps: AgentActivityStep[], event: ActivityEvent): void {
  const at = event.timestamp === undefined ? undefined : new Date(event.timestamp).toISOString()
  if (event.type === 'RUN_STARTED') { steps.splice(0); return }
  if (event.type === 'CUSTOM' && event.name === 'agent_activity_delta' && event.value) {
    const value = event.value
    let step = steps.find(item => item.id === value.id)
    if (!step) { step = { id: value.id, kind: value.kind, label: value.label, status: value.status, detail: '', started_at: value.started_at }; steps.push(step) }
    const detail = step.detail || ''
    const offset = value.detail_offset ?? 0
    if (offset <= detail.length) step.detail = detail + (value.detail_delta || '').slice(detail.length - offset)
    return
  }
  if (event.type === 'CUSTOM' && event.name === 'agent_activity' && event.value) {
    const existing = steps.find(step => step.id === event.value!.id)
    if (existing) Object.assign(existing, event.value)
    else steps.push({ ...event.value })
    return
  }
  if (event.type === 'TOOL_CALL_START') {
    steps.push({ id: `tool:${event.toolCallId}`, kind: 'tool', label: '执行步骤',
      tool_name: event.toolCallName, status: 'running', started_at: at })
    return
  }
  if (event.type === 'TOOL_CALL_RESULT') {
    const step = steps.find(item => item.id === `tool:${event.toolCallId}`)
    if (step) Object.assign(step, { status: 'completed', finished_at: at })
    return
  }
  if (/^(THINKING|REASONING)/.test(event.type) && !event.type.includes('ENCRYPTED')) {
    let step = [...steps].reverse().find(item => item.kind === 'thinking')
    if (event.type.endsWith('START') && step?.status !== 'running') {
      step = { id: `thinking:${steps.filter(item => item.kind === 'thinking').length + 1}`,
        kind: 'thinking', label: '思考过程', status: 'running', detail: '', started_at: at }
      steps.push(step)
    }
    if (step && event.type.endsWith('CONTENT')) step.detail = (step.detail || '') + (event.delta || '')
    if (step && event.type.endsWith('END')) Object.assign(step, { status: 'completed', finished_at: at })
  }
  if (event.type === 'RUN_ERROR' || event.type === 'RUN_FINISHED') {
    for (const step of steps.filter(item => item.status === 'running')) {
      step.status = event.type === 'RUN_ERROR' ? 'failed' : 'completed'
      step.finished_at = at
    }
  }
}

/** A delayed snapshot must not rewind an already streamed or completed step. */
export function mergeActivity(...groups: AgentActivityStep[][]): AgentActivityStep[] {
  const merged = new Map<string, AgentActivityStep>()
  for (const step of groups.flat()) {
    const previous = merged.get(step.id)
    const next = { ...previous, ...step }
    if ((previous?.detail?.length || 0) > (step.detail?.length || 0)) next.detail = previous?.detail
    if (previous && previous.status !== 'running' && step.status === 'running') {
      next.status = previous.status
      next.finished_at = previous.finished_at
    }
    merged.set(step.id, next)
  }
  return [...merged.values()]
}
