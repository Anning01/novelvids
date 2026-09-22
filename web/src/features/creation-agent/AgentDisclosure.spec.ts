import { mount } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import { expect, it } from 'vitest'
import AgentDisclosure from './AgentDisclosure.vue'
import AgentActivity from './AgentActivity.vue'

it('collapses content out of keyboard navigation and restores it without resetting local state', async () => {
  const Draft = defineComponent({ setup: () => ({ text: ref('未提交的草稿') }), template: '<input v-model="text" aria-label="草稿" />' })
  const wrapper = mount(AgentDisclosure, { props: { title: '查询结果', summary: '25 个对象' },
    slots: { default: Draft } })
  const toggle = wrapper.get('button')
  const content = wrapper.get(`#${toggle.attributes('aria-controls')}`)
  expect(toggle.attributes('aria-expanded')).toBe('false')
  expect(content.attributes('inert')).toBeDefined()
  await toggle.trigger('click')
  expect(toggle.attributes('aria-expanded')).toBe('true')
  expect(content.attributes('inert')).toBeUndefined()
  await wrapper.get('input').setValue('更新的草稿')
  await toggle.trigger('click')
  await toggle.trigger('click')
  expect(wrapper.get<HTMLInputElement>('input').element.value).toBe('更新的草稿')
})

it('follows external folding controls and does not emit business actions', async () => {
  const wrapper = mount(AgentDisclosure, { props: { title: '助手回复', open: true }, slots: { default: '完整内容' } })
  await wrapper.setProps({ open: false })
  expect(wrapper.get('button').attributes('aria-expanded')).toBe('false')
  await wrapper.get('button').trigger('click')
  expect(wrapper.emitted('update:open')).toEqual([[true]])
})

it('only animates activity while the real task is active', async () => {
  const wrapper = mount(AgentActivity, { props: { text: '正在整理上下文', active: true } })
  expect(wrapper.get('[role="status"]').text()).toBe('正在整理上下文')
  expect(wrapper.classes()).toContain('is-active')
  await wrapper.setProps({ text: '修改已保存', active: false })
  expect(wrapper.classes()).not.toContain('is-active')
  expect(wrapper.text()).toBe('修改已保存')
})
