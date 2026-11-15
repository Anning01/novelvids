import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import AgentRunActivity from './AgentRunActivity.vue'

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => setTimeout(() => callback(performance.now()), 16))
  vi.stubGlobal('cancelAnimationFrame', (id: number) => clearTimeout(id))
  vi.setSystemTime(new Date('2026-11-07T04:00:10Z'))
})
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

it.each(['light', 'dark'])('follows streaming thought text after rendering in %s mode', async theme => {
  const { reactive, nextTick } = await import('vue')
  document.documentElement.dataset.appTheme = theme
  const steps = reactive<import('./types').AgentActivityStep[]>([
    { id: 'thought', kind: 'thinking', label: '思考过程', status: 'running', detail: '开头' },
  ])
  const wrapper = mount(AgentRunActivity, { props: { status: 2, steps } })
  await nextTick()
  const body = wrapper.get('details p').element as HTMLParagraphElement
  Object.defineProperty(body, 'scrollHeight', { configurable: true, get: () => body.textContent!.length * 20 })
  body.scrollTop = 0
  steps[0]!.detail += '不断追加的内容'
  await nextTick()
  await vi.advanceTimersByTimeAsync(20)
  expect(body.scrollTop).toBe(body.scrollHeight)
  expect(wrapper.emitted('stream-update')?.length).toBeGreaterThan(0)
  const count = wrapper.emitted('stream-update')!.length
  steps[0]!.detail += '最后一段'
  await nextTick()
  await vi.advanceTimersByTimeAsync(20)
  expect(body.scrollTop).toBe(body.scrollHeight)
  expect(wrapper.emitted('stream-update')).toHaveLength(count + 1)
  await wrapper.setProps({ status: 4 })
  const ended = wrapper.emitted('stream-update')!.length
  await wrapper.get('button[aria-label="执行过程"]').trigger('click')
  expect(wrapper.emitted('stream-update')).toHaveLength(ended)
  wrapper.unmount()
  delete document.documentElement.dataset.appTheme
})

it('shows real steps and a ticking elapsed time while the model is running', async () => {
  const wrapper = mount(AgentRunActivity, { props: {
    status: 2, startedAt: '2026-11-07T04:00:00Z', statusText: '正在保存创作调整',
    steps: [
      { id: 'read', kind: 'tool', label: '读取', tool_name: 'read_creation_objects', status: 'completed' },
      { id: 'think', kind: 'thinking', label: '思考', status: 'running', detail: '先确认主角，再调整本章的外貌描述。' },
    ],
  } })
  expect(wrapper.text()).toContain('用时 10 秒')
  expect(wrapper.text()).toContain('查看设定和引用')
  expect(wrapper.get('details').attributes('open')).toBeDefined()
  expect(wrapper.get('details p').text()).toBe('先确认主角，再调整本章的外貌描述。')
  expect(wrapper.findAll('.agent-run-activity__step')).toHaveLength(2)
  await vi.advanceTimersByTimeAsync(51_000)
  expect(wrapper.text()).toContain('用时 1 分 1 秒')
  wrapper.unmount()
  expect(vi.getTimerCount()).toBe(0)
})

it('freezes the recorded duration and retains an expandable reasoning summary after completion', async () => {
  const wrapper = mount(AgentRunActivity, { props: {
    status: 2, startedAt: '2026-11-07T04:00:00Z',
    steps: [{ id: 'thought', kind: 'thinking', label: '思考', status: 'completed', detail: '已核对人物设定。' }],
  } })
  await wrapper.setProps({ status: 3, finishedAt: '2026-11-07T04:00:12Z' })
  await vi.advanceTimersByTimeAsync(30_000)
  expect(wrapper.text()).toContain('用时 12 秒')
  expect(wrapper.find('ol').exists()).toBe(false)
  await wrapper.get('button[aria-label="执行过程"]').trigger('click')
  expect(wrapper.find('details').exists()).toBe(true)
  expect(wrapper.get('details').attributes('open')).toBeUndefined()
  expect(wrapper.find('.is-running').exists()).toBe(false)
  await vi.advanceTimersByTimeAsync(20)
  expect(vi.getTimerCount()).toBe(0)
  wrapper.unmount()
})

it.each([4, 5])('does not keep showing a spinner after terminal status %s', status => {
  const wrapper = mount(AgentRunActivity, { props: {
    status, startedAt: '2026-11-07T04:00:00Z', finishedAt: '2026-11-07T04:00:09Z',
    steps: [{ id: 'save', kind: 'tool', label: '保存创作调整', status: 'running' }],
  } })
  expect(wrapper.text()).toContain(status === 4 ? '本轮未完成' : '本轮已停止')
  expect(wrapper.text()).toContain('用时 9 秒')
  expect(wrapper.find('.agent-run-activity__spinner').exists()).toBe(false)
  wrapper.unmount()
})

it('shows a meaningful current state before steps arrive, without inventing historical timing', () => {
  const wrapper = mount(AgentRunActivity, { props: { status: 2, statusText: '正在准备生成' } })
  expect(wrapper.text()).toContain('正在准备生成')
  expect(wrapper.find('ol').exists()).toBe(false)
  expect(wrapper.find('.agent-run-activity__elapsed').exists()).toBe(false)
  wrapper.unmount()
})

it('does not repeat the operation name in the active summary', () => {
  const wrapper = mount(AgentRunActivity, { props: { status: 2, operationLabel: '图片生成',
    steps: [{ id: 'image', kind: 'status', label: '图片生成', status: 'running' }],
  } })
  expect(wrapper.get('.agent-run-activity__header').text()).toBe('图片生成')
  wrapper.unmount()
})

it.each(['图片生成','视频生成'])('shows the known %s operation instead of connection details',operationLabel=>{
  const wrapper=mount(AgentRunActivity,{props:{status:2,operationLabel,startedAt:'2026-11-07T04:00:00Z',statusText:'任务仍在后台执行，可重新连接查看实时进度'}})
  expect(wrapper.get('.agent-run-activity__header').text()).toContain(operationLabel+'中')
  expect(wrapper.text()).toContain('用时 10 秒')
  expect(wrapper.text()).not.toContain('重新连接')
  wrapper.unmount()
})

it.each(['light', 'dark'])('renders live SDK skill tool states in %s mode without invented summaries', async theme => {
  const { applyActivityEvent } = await import('./activity')
  const { reactive } = await import('vue')
  const steps = reactive<import('./types').AgentActivityStep[]>([])
  document.documentElement.dataset.appTheme = theme
  const wrapper = mount(AgentRunActivity, { props: {
    status: 2, startedAt: '2026-11-07T04:00:00Z', steps,
  } })
  const tool = { id: 'tool:child:read', kind: 'tool' as const, tool_name: 'read_skill',
    label: '执行步骤', status: 'running' as const, started_at: '2026-11-07T04:00:01Z' }
  applyActivityEvent(steps, { type: 'CUSTOM', name: 'agent_activity', value: tool })
  await wrapper.vm.$nextTick()
  expect(wrapper.text()).toContain('正在读取创作规范')
  expect(wrapper.text()).toContain('用时 10 秒')
  expect(wrapper.findAll('.is-running')).toHaveLength(1)
  expect(wrapper.find('details').exists()).toBe(false)
  applyActivityEvent(steps, { type: 'CUSTOM', name: 'agent_activity', value: {
    ...tool, status: 'completed', finished_at: '2026-11-07T04:00:02Z',
  } })
  await wrapper.vm.$nextTick()
  expect(wrapper.text()).toContain('读取创作规范')
  expect(wrapper.text()).toContain('已完成')
  expect(wrapper.find('.agent-run-activity__spinner').exists()).toBe(false)
  await wrapper.setProps({ status: 5, finishedAt: '2026-11-07T04:00:10Z' })
  expect(wrapper.text()).toContain('本轮已停止')
  await wrapper.get('button[aria-label="执行过程"]').trigger('click')
  expect(wrapper.text()).toContain('读取创作规范')
  expect(wrapper.find('details').exists()).toBe(false)
  wrapper.unmount()
  delete document.documentElement.dataset.appTheme
})
