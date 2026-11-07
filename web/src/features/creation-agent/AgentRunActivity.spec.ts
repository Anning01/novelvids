import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import AgentRunActivity from './AgentRunActivity.vue'

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-11-07T04:00:10Z'))
})
afterEach(() => { vi.useRealTimers() })

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
  expect(wrapper.find('details').exists()).toBe(true)
  expect(wrapper.get('details').attributes('open')).toBeUndefined()
  expect(wrapper.find('.is-running').exists()).toBe(false)
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
