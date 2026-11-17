import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import StoryMemoryPanel from './StoryMemoryPanel.vue'
import AppSelect from '@/components/AppSelect.vue'
import { storyMemoryApi } from './api'
import { api } from '@/api'
import { agentApi } from '@/features/creation-agent/api'
import type { AiTask } from '@/types'
import type { MemoryCandidate, MemoryDetail, MemoryStatus } from './types'

vi.mock('./api', () => ({ storyMemoryApi: { status: vi.fn(), context: vi.fn(), history: vi.fn(), detail: vi.fn(), activity: vi.fn(), analyze: vi.fn(), recheck: vi.fn(), update: vi.fn(), review: vi.fn(), decide: vi.fn(), stop: vi.fn() } }))
vi.mock('@/api', async original => ({ ...await original<typeof import('@/api')>(), api: { task: vi.fn() } }))
vi.mock('@/features/creation-agent/api', () => ({ agentApi: { snapshot: vi.fn() } }))
const response = <T,>(data: T) => ({ code: 0, message: '', data })
const candidate: MemoryCandidate = { subjects: [{ ref: 'world', existing_id: 1, kind: 'world', name: '故城世界', aliases: [] }],
  facts: [{ subject_ref: 'world', category: 'world', nature: 'fact', content: '古代王朝，没有电力。',
    scope: { world_ref: 'world', scene: null, from_chapter: null, until_chapter: null, story_time: null },
    evidence: [{ source: 'project.setting', start: 0, end: 10, quote: '古代王朝，没有电力。' }], operation: 'add', replaces_id: null }],
  summary: '古城居民寻找水源。', ending_state: '老周来到古井旁。', unresolved: ['具体朝代未明确'] }
const ready: MemoryDetail = { id: 10, chapter_id: 1, status: 'ready', revision: 1, package_hash: 'a'.repeat(64), current: true,
  stale_reason: null, task_id: 'child', created_at: '2026-11-17T10:00:00Z', decided_at: null,
  candidate, review: { issues: [], summary: '依据、主体与时点已核对。' }, recheck_task_id: null }
const state: MemoryStatus = { baseline: { chapter_id: null, number: null, commit_id: 1, state: 'current', reason: null, can_analyze: true, blocked_by: null },
  chapters: [{ chapter_id: 1, number: 1, commit_id: 9, state: 'current', reason: null, can_analyze: true, blocked_by: null }] }
const task = (status: number, stage?: string): AiTask => ({ id: 'job', task_type: 5, status,
  request_params: {}, response_data: undefined, error_message: undefined, stage, progress: 0,
  created_at: '2026-11-17T10:00:00Z', updated_at: '2026-11-17T10:00:00Z' })
function render(canEdit = true) {
  return mount(StoryMemoryPanel, { props: { projectId: 9, chapterId: 1, canEdit, models: [{ value: '5', label: '分析模型' }], modelId: '5' },
    global: { stubs: { TaskSkillPicker: true, AgentRunActivity: true } } })
}

async function choose(wrapper: ReturnType<typeof render>, label: string, optionLabel: string) {
  const picker = wrapper.findAllComponents(AppSelect).find(component => component.props('ariaLabel') === label)!
  await picker.get('button').trigger('click')
  const menu = document.querySelector(`[role="listbox"][aria-label="${label}"]`)!
  const option = [...menu.querySelectorAll<HTMLButtonElement>('[role="option"]')].find(button => button.textContent?.trim() === optionLabel)!
  expect(option).toBeDefined()
  option.click()
  await flushPromises()
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(storyMemoryApi.status).mockResolvedValue(response(structuredClone(state)))
  vi.mocked(storyMemoryApi.history).mockResolvedValue(response([structuredClone(ready)]))
  vi.mocked(storyMemoryApi.detail).mockResolvedValue(response(structuredClone(ready)))
  vi.mocked(storyMemoryApi.activity).mockResolvedValue(response(null))
  vi.mocked(storyMemoryApi.context).mockResolvedValue(response({ enabled: true, current: { summary: '已确认的背景', ending_state: '', unresolved: [] }, facts: [] }))
  vi.mocked(storyMemoryApi.update).mockResolvedValue(response({ ...structuredClone(ready), revision: 2, status: 'draft', review: {} }))
  vi.mocked(storyMemoryApi.decide).mockResolvedValue(response({ ...structuredClone(ready), status: 'accepted' }))
  vi.mocked(storyMemoryApi.analyze).mockResolvedValue(response(task(3)))
  vi.mocked(storyMemoryApi.recheck).mockResolvedValue(response(task(3)))
  vi.mocked(storyMemoryApi.review).mockResolvedValue(response(task(3)))
  vi.mocked(api.task).mockResolvedValue(response(task(3)))
  vi.mocked(agentApi.snapshot).mockResolvedValue(response({ task_id: 'job', conversation_id: 1, status: 3, content: '',
    error_message: null, changes: [], usage: {}, event_count: 0, activity: [] }))
})
afterEach(() => vi.useRealTimers())

it('separates confirmed memory from reviewable candidates and preserves source evidence', async () => {
  const wrapper = render()
  await flushPromises()
  expect(wrapper.get('h2').text()).toContain('故事记忆')
  expect(wrapper.text()).toContain('当前有效记忆')
  expect(wrapper.text()).toContain('候选与审核')
  expect(wrapper.get('blockquote').text()).toBe('古代王朝，没有电力。')
  expect(wrapper.find('details summary').text()).toBe('原文依据')
  expect(wrapper.findAll('button').find(button => button.text() === '确认并入库')!.attributes('disabled')).toBeUndefined()
  expect(storyMemoryApi.detail).toHaveBeenCalledWith(9, 10, expect.any(AbortSignal))
})

it('switches to global memory through the shared scope picker', async () => {
  const wrapper = render()
  await flushPromises()
  expect(wrapper.find('select').exists()).toBe(false)
  await choose(wrapper, '查看范围', '全局故事底稿')
  expect(storyMemoryApi.context).toHaveBeenLastCalledWith(9, null, expect.any(AbortSignal))
  expect(wrapper.get('button[aria-label="查看范围"]').text()).toContain('全局故事底稿')
})

it.each([['world', '未指定世界', null], [null, '故城世界', 'world']] as const)('saves the world picker value from %s without changing nullable semantics', async (initial, label, expected) => {
  const detail = structuredClone(ready)
  ;(detail.candidate as MemoryCandidate).facts[0]!.scope.world_ref = initial
  vi.mocked(storyMemoryApi.detail).mockResolvedValue(response(detail))
  const wrapper = render()
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === '修改候选')!.trigger('click')
  expect(wrapper.find('select').exists()).toBe(false)
  expect(wrapper.get('button[aria-label="查看范围"]').attributes('disabled')).toBeDefined()
  await choose(wrapper, '所属世界', label)
  await wrapper.setProps({ disabled: true })
  expect(wrapper.get('button[aria-label="所属世界"]').attributes('disabled')).toBeDefined()
  expect(wrapper.get('button[aria-label="记忆性质"]').attributes('disabled')).toBeDefined()
  await wrapper.setProps({ disabled: false })
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(storyMemoryApi.update).toHaveBeenCalledWith(9, 10, expect.objectContaining({
    facts: [expect.objectContaining({ scope: expect.objectContaining({ world_ref: expected }) })],
  }), 1)
})

it('uses the reviewed package hash and records the human decision note', async () => {
  const wrapper = render()
  await flushPromises()
  await wrapper.get('textarea[name="decision_note"]').setValue('已核对剧本，确认古代背景。')
  await wrapper.findAll('button').find(button => button.text() === '确认并入库')!.trigger('click')
  await flushPromises()
  expect(storyMemoryApi.decide).toHaveBeenCalledWith(9, 10, 'a'.repeat(64), 'accept', '已核对剧本，确认古代背景。')
  expect(wrapper.get('[role="status"]').text()).toContain('记忆已正式提交')
})

it('edits a candidate without altering the evidence and invalidates its prior review', async () => {
  const wrapper = render()
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === '修改候选')!.trigger('click')
  await wrapper.get('textarea[name="fact_0"]').setValue('古代城镇，以油灯照明。')
  await choose(wrapper, '记忆性质', '人物证言')
  await wrapper.get('input[name="scene_0"]').setValue('灾变前的回忆')
  await wrapper.get('input[name="from_0"]').setValue('2')
  await wrapper.get('input[name="until_0"]').setValue('3')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(storyMemoryApi.update).toHaveBeenCalledWith(9, 10, expect.objectContaining({ facts: [expect.objectContaining({
    content: '古代城镇，以油灯照明。', nature: 'testimony', evidence: candidate.facts[0]!.evidence,
    scope: expect.objectContaining({ scene: '灾变前的回忆', from_chapter: 2, until_chapter: 3 }),
  })] }), 1)
  expect(wrapper.text()).toContain('候选已保存，请重新审核后再确认')
  expect(wrapper.findAll('button').find(button => button.text() === '确认并入库')!.attributes('disabled')).toBeDefined()
})

it('prevents approving blocking reviews or stale editions', async () => {
  vi.mocked(storyMemoryApi.detail).mockResolvedValue(response({ ...structuredClone(ready), status: 'needs_review',
    review: { summary: '发现问题', issues: [{ severity: 'blocking', fact_index: 0, reason: '年代与正文冲突' }] } }))
  const wrapper = render()
  await flushPromises()
  expect(wrapper.text()).toContain('年代与正文冲突')
  expect(wrapper.findAll('button').find(button => button.text() === '确认并入库')!.attributes('disabled')).toBeDefined()
  vi.mocked(storyMemoryApi.detail).mockResolvedValue(response({ ...structuredClone(ready), status: 'stale', current: false, stale_reason: '剧本已变化' }))
  await wrapper.setProps({ projectId: 10 })
  await flushPromises()
  expect(wrapper.text()).toContain('剧本已变化')
  expect(wrapper.findAll('button').some(button => button.text() === '确认并入库')).toBe(false)
  expect(storyMemoryApi.decide).not.toHaveBeenCalled()
})

it('preserves a candidate when the server rejects an outdated confirmation', async () => {
  vi.mocked(storyMemoryApi.decide).mockRejectedValue(new Error('候选版本已变化，请重新核对'))
  const wrapper = render()
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === '确认并入库')!.trigger('click')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('候选版本已变化')
  expect(wrapper.get('blockquote').text()).toBe(candidate.facts[0]!.evidence[0]!.quote)
})

it('keeps review and mutation controls out of a viewer session', async () => {
  const wrapper = render(false)
  await flushPromises()
  expect(wrapper.text()).toContain('古代王朝，没有电力。')
  for (const label of ['确认并入库', '修改候选', '退回候选', '顺序复核全部']) expect(wrapper.findAll('button').some(button => button.text() === label)).toBe(false)
})

it('starts sequential review explicitly and does not start work on load', async () => {
  const wrapper = render()
  await flushPromises()
  expect(storyMemoryApi.recheck).not.toHaveBeenCalled()
  await wrapper.findAll('button').find(button => button.text() === '顺序复核全部')!.trigger('click')
  await flushPromises()
  expect(storyMemoryApi.recheck).toHaveBeenCalledWith(9, 5, undefined)
  expect(wrapper.text()).toContain('本轮已完成，请核对记忆')
})

it('announces request failures and provides a read retry', async () => {
  vi.mocked(storyMemoryApi.status).mockRejectedValueOnce(new Error('连接中断'))
  const wrapper = render()
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('连接中断')
  await wrapper.findAll('button').find(button => button.text() === '重试读取记忆')!.trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('候选与审核')
})

it('stops polling on unmount', async () => {
  vi.useFakeTimers()
  vi.mocked(storyMemoryApi.activity).mockResolvedValue(response(task(2)))
  vi.mocked(api.task).mockResolvedValue(response(task(2)))
  const wrapper = render()
  await flushPromises()
  const calls = vi.mocked(api.task).mock.calls.length
  wrapper.unmount()
  await vi.advanceTimersByTimeAsync(4000)
  expect(api.task).toHaveBeenCalledTimes(calls)
})

it('retains an unsaved candidate when a script update arrives', async () => {
  const wrapper = render()
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === '修改候选')!.trigger('click')
  await wrapper.get('textarea[name="summary"]').setValue('仍在编辑的世界观说明')
  await wrapper.setProps({ refreshKey: 2 })
  expect((wrapper.get('textarea[name="summary"]').element as HTMLTextAreaElement).value).toBe('仍在编辑的世界观说明')
  expect(wrapper.get('[role="alert"]').text()).toContain('当前候选草稿仍保留')
  expect(storyMemoryApi.update).not.toHaveBeenCalled()
})

it('ignores a late chapter response after switching scopes', async () => {
  let resolve!: (value: ReturnType<typeof response<MemoryDetail>>) => void
  const delayed = new Promise<ReturnType<typeof response<MemoryDetail>>>(done => { resolve = done })
  vi.mocked(storyMemoryApi.status).mockResolvedValue(response({ ...state, chapters: [...state.chapters,
    { ...state.chapters[0]!, chapter_id: 2, number: 2, commit_id: 20 }] }))
  const next = { ...structuredClone(ready), id: 20, chapter_id: 2, candidate: { ...structuredClone(candidate), summary: '第二章的独立世界' } }
  vi.mocked(storyMemoryApi.history).mockResolvedValue(response([ready, next]))
  vi.mocked(storyMemoryApi.detail).mockImplementation(async (_project, identifier) => identifier === 10 ? delayed : response(next))
  const wrapper = render()
  await flushPromises()
  await choose(wrapper, '查看范围', '第 2 集 · 已确认')
  await flushPromises()
  resolve(response(ready))
  await flushPromises()
  expect(wrapper.get('.memory-candidate').text()).toContain('第二章的独立世界')
  expect(wrapper.get('.memory-candidate').text()).not.toContain('古城居民寻找水源。')
})

it('does not carry a late confirmation into another project', async () => {
  let resolve!: (value: ReturnType<typeof response<MemoryDetail>>) => void
  vi.mocked(storyMemoryApi.decide).mockReturnValue(new Promise(done => { resolve = done }))
  const wrapper = render()
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === '确认并入库')!.trigger('click')
  await wrapper.setProps({ projectId: 20 })
  await flushPromises()
  resolve(response({ ...ready, status: 'accepted' }))
  await flushPromises()
  expect(wrapper.text()).not.toContain('记忆已正式提交')
  expect(wrapper.findAll('button').find(button => button.text() === '确认并入库')!.attributes('disabled')).toBeUndefined()
})

it('renders source markup as text rather than executable HTML', async () => {
  const unsafe = structuredClone(ready)
  ;(unsafe.candidate as MemoryCandidate).facts[0]!.evidence[0]!.quote = '<script>window.bad = true</script>'
  vi.mocked(storyMemoryApi.detail).mockResolvedValue(response(unsafe))
  const wrapper = render()
  await flushPromises()
  expect(wrapper.get('blockquote').text()).toBe('<script>window.bad = true</script>')
  expect(wrapper.find('script').exists()).toBe(false)
})
