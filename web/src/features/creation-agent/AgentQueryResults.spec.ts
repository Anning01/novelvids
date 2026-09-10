import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import AgentQueryResults from './AgentQueryResults.vue'

it('lets users locate query matches and specify a target without sending a request', async () => {
  const item = { kind: 'asset' as const, id: 7, name: '蓝色雨衣' }
  const wrapper = mount(AgentQueryResults, { props: { result: { items: [item], total: 21, has_more: true }, disabled: false } })
  await wrapper.get('button[title="蓝色雨衣"]').trigger('click')
  expect(wrapper.emitted('locate')).toEqual([[item]])
  await wrapper.get('[aria-label="指定蓝色雨衣"]').trigger('click')
  expect(wrapper.emitted('select')).toEqual([[item]])
  expect(wrapper.text()).toContain('下一页')
  await wrapper.setProps({ disabled: true })
  expect(wrapper.get('[aria-label="指定蓝色雨衣"]').attributes('disabled')).toBeDefined()
})
