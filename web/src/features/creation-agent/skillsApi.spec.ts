import { expect, it, vi, afterEach } from 'vitest'
import { runSkillTrial, type SkillTrialEvent, type SkillTrialInput } from './skillsApi'

const body: SkillTrialInput = { skill: { task: 'story', name: 'test', description: '', instructions: '# 方法', references: [], is_active: true }, input: '原文', model_config_id: 2, thinking: null, reasoning_effort: null }
afterEach(() => vi.unstubAllGlobals())
it('decodes split UTF-8 and partial SSE frames without dropping Chinese output', async () => {
  const bytes = new TextEncoder().encode('data: {"type":"output","delta":"中文"}\n\ndata: {"type":"done"}\n\n')
  vi.stubGlobal('fetch', vi.fn(async () => new Response(new ReadableStream({ start(controller) {
    for (let index = 0; index < bytes.length; index++) controller.enqueue(bytes.slice(index, index + 1))
    controller.close()
  } }))))
  const events: SkillTrialEvent[] = []
  await runSkillTrial(body, new AbortController().signal, event => events.push(event))
  expect(events).toEqual([{ type: 'output', delta: '中文' }, { type: 'done' }])
})
it('treats a truncated stream as a failure instead of a successful trial', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('data: {"type":"output","delta":"partial"}\n\n')))
  await expect(runSkillTrial(body, new AbortController().signal, vi.fn())).rejects.toThrow('连接中断')
})
