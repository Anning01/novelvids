import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import StoryMemoryPanel from './StoryMemoryPanel.vue'
import AppSelect from '@/components/AppSelect.vue'
import { storyMemoryApi } from './api'
import { api } from '@/api'
import { notice } from '@/shared/notice'
import type { AiTask } from '@/types'
import type { MemoryCandidate, MemoryDetail, MemoryStatus } from './types'

vi.mock('./api', () => ({ storyMemoryApi: { status: vi.fn(), context: vi.fn(), history: vi.fn(), detail: vi.fn(), activity: vi.fn(), analyze: vi.fn(), recheck: vi.fn(), update: vi.fn(), review: vi.fn(), repair: vi.fn(), decide: vi.fn() } }))
vi.mock('@/api', async original => ({ ...await original<typeof import('@/api')>(), api: { task: vi.fn() } }))
vi.mock('@/shared/notice', () => ({ notice: { error: vi.fn(), success: vi.fn() } }))
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
let reviewHost: HTMLElement
let review: DOMWrapper<HTMLElement>
function render(canEdit = true, showAssistant = true) {
  return mount(StoryMemoryPanel, { props: { projectId: 9, chapterId: 1, canEdit, reviewTarget: showAssistant ? reviewHost : null, models: [{ value: '5', label: '分析模型' }], modelId: '5' },
    global: { stubs: { TaskSkillPicker: true } } })
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
  reviewHost = document.createElement('aside')
  document.body.append(reviewHost)
  review = new DOMWrapper(reviewHost)
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
})
afterEach(() => { reviewHost.remove(); vi.useRealTimers() })

it('separates confirmed memory from reviewable candidates and preserves source evidence', async () => {
  const wrapper = render()
  await flushPromises()
  expect(wrapper.get('h2').text()).toContain('故事记忆')
  expect(wrapper.text()).toContain('当前有效记忆')
  expect(wrapper.text()).not.toContain('候选与审核')
  expect(review.text()).toContain('候选与审核')
  expect(review.get('blockquote').text()).toBe('古代王朝，没有电力。')
  expect(review.find('details summary').text()).toBe('原文依据')
  expect(review.findAll('button').find(button => button.text() === '确认并入库')!.attributes('disabled')).toBeUndefined()
  expect(storyMemoryApi.detail).toHaveBeenCalledWith(9, 10, expect.any(AbortSignal))
})

it('keeps confirmed memory in a dialog and closes it when the selected scope changes', async () => {
  vi.mocked(storyMemoryApi.context).mockResolvedValue(response({
    enabled: true,
    current: { summary: '已确认的章节摘要', ending_state: '', unresolved: [] },
    facts: [{ id: 12, subject: { id: 1, kind: 'world', name: '故城世界', aliases: [] },
      category: 'world', nature: 'fact', content: '以油灯照明。', evidence: candidate.facts[0]!.evidence, scope: {} }],
  }))
  const wrapper = render()
  await flushPromises()
  expect(wrapper.text()).not.toContain('已确认的章节摘要')
  const trigger = wrapper.findAll('button').find(button => button.text() === '查看当前有效记忆')!
  const dialog = document.getElementById(trigger.attributes('aria-controls') ?? '') as HTMLDialogElement
  expect(dialog.open).toBe(false)
  await trigger.trigger('click')
  expect(dialog.open).toBe(true)
  expect(dialog.textContent).toContain('已确认的章节摘要')
  expect(dialog.textContent).toContain('查看已确认事实（1）')
  expect(dialog.querySelector('blockquote')?.textContent).toBe('古代王朝，没有电力。')
  await choose(wrapper, '查看范围', '全局故事底稿')
  expect(dialog.open).toBe(false)
  expect(dialog.textContent).not.toContain('已确认的章节摘要')
})

it('opens candidate review in the assistant and preserves a draft across close and reopen', async () => {
  const wrapper = render(true, false)
  await flushPromises()
  expect(review.find('section').exists()).toBe(false)
  await wrapper.findAll('button').find(button => button.text() === '在创作助手查看候选')!.trigger('click')
  expect(wrapper.emitted('showRun')).toEqual([[]])
  await wrapper.setProps({ reviewTarget: reviewHost })
  expect(document.activeElement).toBe(review.get('h3').element)
  await review.findAll('button').find(button => button.text() === '修改候选')!.trigger('click')
  await review.get('textarea[name="summary"]').setValue('未保存的修改')
  await wrapper.setProps({ reviewTarget: null })
  expect(review.find('section').exists()).toBe(false)
  await wrapper.setProps({ reviewTarget: reviewHost })
  expect(review.get<HTMLTextAreaElement>('textarea[name="summary"]').element.value).toBe('未保存的修改')
  expect(wrapper.find('.memory-candidate').exists()).toBe(false)
})

it('switches to global memory through the shared scope picker', async () => {
  const wrapper = render()
  await flushPromises()
  expect(wrapper.find('select').exists()).toBe(false)
  await choose(wrapper, '查看范围', '全局故事底稿')
  expect(storyMemoryApi.context).toHaveBeenLastCalledWith(9, null, expect.any(AbortSignal))
  expect(wrapper.get('button[aria-label="查看范围"]').text()).toContain('全局故事底稿')
  await wrapper.setProps({ chapterSelectionKey: 1 })
  await flushPromises()
  expect(wrapper.get('button[aria-label="查看范围"]').text()).toContain('第 1 集')
})

it('keeps the viewed chapter while offering direct access to the batch candidate', async () => {
  const baseline = { ...ready, id: 12, chapter_id: null, status: 'needs_review' as const }
  vi.mocked(storyMemoryApi.history).mockResolvedValue(response([]))
  vi.mocked(storyMemoryApi.status).mockResolvedValue(response({
    ...state, baseline: { ...state.baseline, candidate_id: 12, candidate_status: 'needs_review' },
  }))
  vi.mocked(storyMemoryApi.detail).mockImplementation(async (_project, id) => response(id === 12 ? baseline : ready))
  vi.mocked(storyMemoryApi.activity).mockResolvedValue(response(task(2, 'needs_review')))
  vi.mocked(api.task).mockResolvedValue(response({ ...task(2, 'needs_review'), response_data: { waiting_commit_id: 12 } }))
  const wrapper = render()
  await flushPromises()
  expect(wrapper.get('button[aria-label="查看范围"]').text()).toContain('第 1 集')
  await wrapper.findAll('button').find(button => button.text() === '查看待处理候选')!.trigger('click')
  await flushPromises()
  expect(wrapper.get('button[aria-label="查看范围"]').text()).toContain('全局故事底稿')
  expect(review.text()).toContain('按审核意见补全')
  expect(storyMemoryApi.detail).toHaveBeenLastCalledWith(9, 12, expect.any(AbortSignal))
  expect(storyMemoryApi.analyze).not.toHaveBeenCalled()
  expect(storyMemoryApi.recheck).not.toHaveBeenCalled()
})

it.each([['world', '未指定世界', null], [null, '故城世界', 'world']] as const)('saves the world picker value from %s without changing nullable semantics', async (initial, label, expected) => {
  const detail = structuredClone(ready)
  ;(detail.candidate as MemoryCandidate).facts[0]!.scope.world_ref = initial
  vi.mocked(storyMemoryApi.detail).mockResolvedValue(response(detail))
  const wrapper = render()
  await flushPromises()
  await review.findAll('button').find(button => button.text() === '修改候选')!.trigger('click')
  expect(wrapper.find('select').exists()).toBe(false)
  expect(wrapper.get('button[aria-label="查看范围"]').attributes('disabled')).toBeDefined()
  await choose(wrapper, '所属世界', label)
  await wrapper.setProps({ disabled: true })
  expect(review.get('button[aria-label="所属世界"]').attributes('disabled')).toBeDefined()
  expect(review.get('button[aria-label="记忆性质"]').attributes('disabled')).toBeDefined()
  await wrapper.setProps({ disabled: false })
  await review.get('form').trigger('submit')
  await flushPromises()
  expect(storyMemoryApi.update).toHaveBeenCalledWith(9, 10, expect.objectContaining({
    facts: [expect.objectContaining({ scope: expect.objectContaining({ world_ref: expected }) })],
  }), 1)
})

it('uses the reviewed package hash and records the human decision note', async () => {
  render()
  await flushPromises()
  await review.get('textarea[name="decision_note"]').setValue('已核对剧本，确认古代背景。')
  await review.findAll('button').find(button => button.text() === '确认并入库')!.trigger('click')
  await flushPromises()
  expect(storyMemoryApi.decide).toHaveBeenCalledWith(9, 10, 'a'.repeat(64), 'accept', '已核对剧本，确认古代背景。')
  expect(notice.success).toHaveBeenCalledWith('记忆已正式提交')
})

it('edits a candidate without altering the evidence and invalidates its prior review', async () => {
  const wrapper = render()
  await flushPromises()
  await review.findAll('button').find(button => button.text() === '修改候选')!.trigger('click')
  await review.get('textarea[name="fact_0"]').setValue('古代城镇，以油灯照明。')
  await choose(wrapper, '记忆性质', '人物证言')
  await review.get('input[name="scene_0"]').setValue('灾变前的回忆')
  await review.get('input[name="from_0"]').setValue('2')
  await review.get('input[name="until_0"]').setValue('3')
  await review.get('form').trigger('submit')
  await flushPromises()
  expect(storyMemoryApi.update).toHaveBeenCalledWith(9, 10, expect.objectContaining({ facts: [expect.objectContaining({
    content: '古代城镇，以油灯照明。', nature: 'testimony', evidence: candidate.facts[0]!.evidence,
    scope: expect.objectContaining({ scene: '灾变前的回忆', from_chapter: 2, until_chapter: 3 }),
  })] }), 1)
  expect(notice.success).toHaveBeenCalledWith('候选已保存，请重新审核后再确认')
  expect(review.text()).toContain('候选尚未审核，请先重新审核。')
  expect(review.findAll('button').find(button => button.text() === '确认并入库')!.attributes('disabled')).toBeDefined()
})

it('offers repair or rejection while blocked and prevents editing stale editions', async () => {
  vi.mocked(storyMemoryApi.detail).mockResolvedValue(response({ ...structuredClone(ready), status: 'needs_review',
    review: { summary: '发现问题', issues: [{ severity: 'blocking', fact_index: 0, reason: '年代与正文冲突' }] } }))
  const wrapper = render()
  await flushPromises()
  expect(review.text()).toContain('年代与正文冲突')
  expect(review.text()).not.toContain('确认并入库')
  expect(review.text()).toContain('按审核意见补全')
  expect(review.text()).toContain('退回候选')
  await review.findAll('button').find(button => button.text() === '查看审核意见')!.trigger('click')
  expect(document.activeElement).toBe(review.get('[aria-label="审核意见"]').element)
  vi.mocked(storyMemoryApi.detail).mockResolvedValue(response({ ...structuredClone(ready), status: 'stale', current: false, stale_reason: '剧本已变化' }))
  await wrapper.setProps({ projectId: 10 })
  await flushPromises()
  expect(review.text()).toContain('剧本已变化')
  expect(review.findAll('button').some(button => button.text() === '确认并入库')).toBe(false)
  expect(storyMemoryApi.decide).not.toHaveBeenCalled()
})

it('requests a repair for the reviewed version and presents the new result for human confirmation', async () => {
  const blocked = { ...structuredClone(ready), status: 'needs_review' as const }
  vi.mocked(storyMemoryApi.detail).mockResolvedValue(response(blocked))
  const wrapper = render()
  await flushPromises()
  vi.mocked(storyMemoryApi.repair).mockResolvedValue(response(task(3)))
  vi.mocked(storyMemoryApi.detail).mockResolvedValue(response({
    ...ready, revision: 2, package_hash: 'b'.repeat(64),
    candidate: { ...candidate, summary: '根据原文补齐了遗漏的事实。' },
  }))
  await review.findAll('button').find(button => button.text() === '按审核意见补全')!.trigger('click')
  await flushPromises()
  expect(storyMemoryApi.repair).toHaveBeenCalledWith(9, 10, 1, 'a'.repeat(64), 5)
  expect(wrapper.emitted('showRun')).toBeDefined()
  expect(review.text()).toContain('根据原文补齐了遗漏的事实。')
  expect(review.findAll('button').find(button => button.text() === '确认并入库')!.attributes('disabled')).toBeUndefined()
  expect(storyMemoryApi.decide).not.toHaveBeenCalled()
})

it('preserves a candidate when the server rejects an outdated confirmation', async () => {
  vi.mocked(storyMemoryApi.decide).mockRejectedValue(new Error('候选版本已变化，请重新核对'))
  render()
  await flushPromises()
  await review.findAll('button').find(button => button.text() === '确认并入库')!.trigger('click')
  await flushPromises()
  expect(notice.error).toHaveBeenCalledWith('候选版本已变化，请重新核对')
  expect(review.get('blockquote').text()).toBe(candidate.facts[0]!.evidence[0]!.quote)
})

it('keeps review and mutation controls out of a viewer session', async () => {
  const wrapper = render(false)
  await flushPromises()
  expect(review.text()).toContain('古代王朝，没有电力。')
  for (const label of ['确认并入库', '修改候选', '退回候选', '顺序复核全部']) expect(wrapper.findAll('button').concat(review.findAll('button')).some(button => button.text() === label)).toBe(false)
})

it('starts sequential review explicitly and does not start work on load', async () => {
  const wrapper = render()
  await flushPromises()
  expect(storyMemoryApi.recheck).not.toHaveBeenCalled()
  await wrapper.findAll('button').find(button => button.text() === '顺序复核全部')!.trigger('click')
  await flushPromises()
  expect(storyMemoryApi.recheck).toHaveBeenCalledWith(9, 5, undefined)
  expect(wrapper.text()).not.toContain('候选与审核')
  expect(review.text()).toContain('候选与审核')
})

it('omits history and failed run details from the main page while keeping the assistant link', async () => {
  vi.mocked(storyMemoryApi.activity).mockResolvedValue(response(task(4)))
  vi.mocked(api.task).mockResolvedValue(response({
    ...task(4), request_params: { conversation_id: 42 }, error_message: '本章分析未完成',
  }))
  const wrapper = render()
  await flushPromises()
  expect(wrapper.text()).not.toContain('提交历史')
  expect(wrapper.text()).not.toContain('本章分析未完成')
  expect(notice.error).not.toHaveBeenCalled()
  await wrapper.get('.memory-header').findAll('button').find(button => button.text() === '在创作助手查看进度')!.trigger('click')
  expect(wrapper.emitted('showRun')).toEqual([[{ taskId: 'job', conversationId: 42 }]])
})

it('opens the assistant for a queued review and hands off to its conversation when ready', async () => {
  vi.mocked(storyMemoryApi.recheck).mockResolvedValue(response(task(6)))
  vi.mocked(api.task).mockResolvedValue(response({
    ...task(2, 'rechecking_story'), request_params: { conversation_id: 42 }, response_data: { completed: [{}], total: 185 },
  }))
  const wrapper = render()
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === '顺序复核全部')!.trigger('click')
  await flushPromises()
  expect(wrapper.emitted('showRun')).toEqual([[], [{ taskId: 'job', conversationId: 42 }]])
  expect(wrapper.find('progress').exists()).toBe(false)
  expect(wrapper.find('.agent-run-activity').exists()).toBe(false)
  expect(wrapper.text()).not.toContain('停止本轮')
  expect(wrapper.text()).toContain('在创作助手查看进度')
  const polls = vi.mocked(api.task).mock.calls.length
  await wrapper.findAll('button').find(button => button.text() === '在创作助手查看进度')!.trigger('click')
  expect(api.task).toHaveBeenCalledTimes(polls)
  expect(storyMemoryApi.recheck).toHaveBeenCalledTimes(1)
})

it('announces request failures and provides a read retry', async () => {
  vi.mocked(storyMemoryApi.status).mockRejectedValueOnce(new Error('连接中断'))
  const wrapper = render()
  await flushPromises()
  expect(notice.error).toHaveBeenCalledWith('连接中断')
  await wrapper.findAll('button').find(button => button.text() === '刷新记忆')!.trigger('click')
  await flushPromises()
  expect(wrapper.text()).not.toContain('候选与审核')
  expect(review.text()).toContain('候选与审核')
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
  await review.findAll('button').find(button => button.text() === '修改候选')!.trigger('click')
  await review.get('textarea[name="summary"]').setValue('仍在编辑的世界观说明')
  await wrapper.setProps({ refreshKey: 2 })
  expect((review.get('textarea[name="summary"]').element as HTMLTextAreaElement).value).toBe('仍在编辑的世界观说明')
  expect(notice.error).toHaveBeenCalledWith(expect.stringContaining('当前候选草稿仍保留'))
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
  expect(review.get('.memory-candidate').text()).toContain('第二章的独立世界')
  expect(review.get('.memory-candidate').text()).not.toContain('古城居民寻找水源。')
})

it('does not carry a late confirmation into another project', async () => {
  let resolve!: (value: ReturnType<typeof response<MemoryDetail>>) => void
  vi.mocked(storyMemoryApi.decide).mockReturnValue(new Promise(done => { resolve = done }))
  const wrapper = render()
  await flushPromises()
  await review.findAll('button').find(button => button.text() === '确认并入库')!.trigger('click')
  await wrapper.setProps({ projectId: 20 })
  await flushPromises()
  resolve(response({ ...ready, status: 'accepted' }))
  await flushPromises()
  expect(notice.success).not.toHaveBeenCalled()
  expect(review.findAll('button').find(button => button.text() === '确认并入库')!.attributes('disabled')).toBeUndefined()
})

it('renders source markup as text rather than executable HTML', async () => {
  const unsafe = structuredClone(ready)
  ;(unsafe.candidate as MemoryCandidate).facts[0]!.evidence[0]!.quote = '<script>window.bad = true</script>'
  vi.mocked(storyMemoryApi.detail).mockResolvedValue(response(unsafe))
  render()
  await flushPromises()
  expect(review.get('blockquote').text()).toBe('<script>window.bad = true</script>')
  expect(review.find('script').exists()).toBe(false)
})

it('offers no confirmation for an empty global candidate', async () => {
  const empty = { ...ready, chapter_id: null, candidate: { ...candidate, facts: [], subjects: [] } }
  vi.mocked(storyMemoryApi.history).mockResolvedValue(response([empty]))
  vi.mocked(storyMemoryApi.detail).mockResolvedValue(response(empty))
  const wrapper = render()
  await flushPromises()
  await choose(wrapper, '查看范围', '全局故事底稿')
  expect(review.text()).toContain('全局故事底稿没有可确认事实')
  expect(review.text()).not.toContain('确认并入库')
  expect(storyMemoryApi.decide).not.toHaveBeenCalled()
})
