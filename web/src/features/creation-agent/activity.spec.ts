import { expect, it } from 'vitest'
import { applyActivityEvent } from './activity'
import type { AgentActivityStep } from './types'

it('appends batched Unicode deltas once and tolerates an overlapping snapshot', () => {
  const steps: AgentActivityStep[] = []
  const value = { id: 'thought', kind: 'thinking' as const, label: '思考', status: 'running' as const }
  applyActivityEvent(steps, { type: 'CUSTOM', name: 'agent_activity', value: { ...value, detail: '🐱' } })
  const event = { type: 'CUSTOM', name: 'agent_activity_delta', value: { ...value, detail_offset: 2, detail_delta: '新内容' } }
  applyActivityEvent(steps, event)
  applyActivityEvent(steps, event)
  expect(steps[0]!.detail).toBe('🐱新内容')
  applyActivityEvent(steps, { type: 'CUSTOM', name: 'agent_activity_delta', value: { ...value, detail_offset: 2, detail_delta: '新内容继续' } })
  expect(steps[0]!.detail).toBe('🐱新内容继续')
})

it('shows actual reasoning and tool execution without exposing arguments or results', () => {
  const steps: AgentActivityStep[] = []
  applyActivityEvent(steps, { type: 'REASONING_START', timestamp: 1000 })
  applyActivityEvent(steps, { type: 'REASONING_MESSAGE_START', timestamp: 1001 })
  applyActivityEvent(steps, { type: 'REASONING_MESSAGE_CONTENT', delta: '先核对主角' })
  applyActivityEvent(steps, { type: 'REASONING_MESSAGE_CONTENT', delta: '与章节的对应关系。' })
  applyActivityEvent(steps, { type: 'REASONING_MESSAGE_END', timestamp: 2000 })
  applyActivityEvent(steps, { type: 'TOOL_CALL_START', toolCallId: 'read', toolCallName: 'read_creation_objects', timestamp: 2100 })
  applyActivityEvent(steps, { type: 'TOOL_CALL_ARGS', toolCallId: 'read', delta: 'private parameters' })
  expect(steps).toHaveLength(2)
  expect(steps[0]).toMatchObject({ detail: '先核对主角与章节的对应关系。', status: 'completed' })
  expect(steps[1]?.status).toBe('running')
  applyActivityEvent(steps, { type: 'TOOL_CALL_RESULT', toolCallId: 'read', timestamp: 3000 })
  expect(steps[1]).toMatchObject({ status: 'completed', finished_at: new Date(3000).toISOString() })
  expect(JSON.stringify(steps)).not.toContain('private parameters')
})

it('replays without duplicating reasoning and updates real child model progress by id', () => {
  const steps: AgentActivityStep[] = []
  for (let replay = 0; replay < 2; replay++) {
    applyActivityEvent(steps, { type: 'RUN_STARTED' })
    applyActivityEvent(steps, { type: 'THINKING_START' })
    applyActivityEvent(steps, { type: 'THINKING_TEXT_MESSAGE_START' })
    applyActivityEvent(steps, { type: 'THINKING_TEXT_MESSAGE_CONTENT', delta: '实际摘要' })
    applyActivityEvent(steps, { type: 'THINKING_END' })
  }
  expect(steps).toHaveLength(1)
  expect(steps[0]?.detail).toBe('实际摘要')
  const child: AgentActivityStep = { id: 'model:child:1', label: '提取本章资产', kind: 'status', status: 'running' }
  applyActivityEvent(steps, { type: 'CUSTOM', name: 'agent_activity', value: child })
  applyActivityEvent(steps, { type: 'CUSTOM', name: 'agent_activity', value: { ...child, status: 'completed' } })
  expect(steps).toHaveLength(2)
  expect(steps[1]?.status).toBe('completed')
  applyActivityEvent(steps, { type: 'TOOL_CALL_START', toolCallId: 'save' })
  applyActivityEvent(steps, { type: 'RUN_ERROR', timestamp: 4000 })
  expect(steps[2]?.status).toBe('failed')
  expect(steps[1]?.status).toBe('completed')
})

it('does not lose a child step or rewind a completed step when snapshots arrive late', async () => {
  const { mergeActivity } = await import('./activity')
  const completed: AgentActivityStep = { id: 'thinking:1', kind: 'thinking', label: '思考', status: 'completed', detail: '完整的思考摘要', finished_at: '2026-11-07T00:00:03Z' }
  const child: AgentActivityStep = { id: 'model:child:1', kind: 'status', label: '提取资产', status: 'running' }
  const merged = mergeActivity([completed, child], [{ ...completed, status: 'running', detail: '完整', finished_at: undefined }])
  expect(merged).toEqual([completed, child])
})
