import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import PromptChangeCard from './PromptChangeCard.vue'
import type { AgentChange } from './types'

const change: AgentChange = { id: 1, task_id: 'run', created_at: '', reverted_at: null,
  changes: [{ kind: 'scene', target_id: 5, target_label: '雨夜空镜', operation: 'delete',
    before: { description: '空站台', prompt: '完整雨夜画面' }, after: {}, after_version: 'version' }] }

it('shows deleted content and undo without linking to a hidden object', async () => {
  const wrapper = mount(PromptChangeCard, { props: { change, canUndo: true } })
  await wrapper.findAll('button').find(button => button.text() === '查看差异')!.trigger('click')
  expect(wrapper.text()).toContain('已移除')
  expect(wrapper.text()).toContain('完整雨夜画面')
  expect(wrapper.findAll('button').some(button => button.text() === '雨夜空镜')).toBe(false)
  await wrapper.findAll('button').find(button => button.text() === '撤销这次修改')!.trigger('click')
  expect(wrapper.emitted('undo')).toEqual([[1]])
  await wrapper.setProps({ change: { ...change, reverted_at: '2026-09-10' } })
  await wrapper.findAll('button').find(button => button.text() === '雨夜空镜')!.trigger('click')
  expect(wrapper.emitted('locate')).toEqual([[change.changes[0]]])
})

it('renders setting field changes and preserves legacy prompt history', async () => {
  const wrapper = mount(PromptChangeCard, { props: { canUndo: true, change: { ...change, changes: [{
    kind: 'asset', target_id: 8, before: { description: '原描述', base_traits: '原提示词' },
    after: { description: '新描述', base_traits: '新提示词' }, after_version: 'version',
  }] } } })
  await wrapper.findAll('button').find(button => button.text() === '查看差异')!.trigger('click')
  expect(wrapper.text()).toContain('已保存')
  expect(wrapper.text()).toContain('原描述')
  expect(wrapper.text()).toContain('新提示词')
})
