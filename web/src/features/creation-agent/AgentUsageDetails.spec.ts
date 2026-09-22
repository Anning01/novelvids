import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import AgentUsageDetails from './AgentUsageDetails.vue'

it('distinguishes missing cache usage from a reported zero and keeps details collapsed', () => {
  const wrapper = mount(AgentUsageDetails, { props: { usage: { requests: 2, input_tokens: 1000, output_tokens: 50, cache_read_tokens: 800, cache_usage_reported: true, cache_price_configured: false } } })
  expect(wrapper.text()).toContain('80.0%')
  expect(wrapper.text()).toContain('尚未配置缓存输入单价')
  expect(wrapper.get('details').attributes('open')).toBeUndefined()
  const missing = mount(AgentUsageDetails, { props: { usage: { requests: 1 } } })
  expect(missing.text()).toContain('供应商未完整报告')
  const zero = mount(AgentUsageDetails, { props: { usage: { requests: 1, input_tokens: 100, cache_usage_reported: true } } })
  expect(zero.text()).toContain('0.0%')
})

it('shows scoped saved rules without exposing internal identifiers', () => {
  const wrapper = mount(AgentUsageDetails, { props: { usage: { remembered_rules: [{ content: '统一冷光', scope: { kind: 'chapter', chapter_id: 42 } }] } } })
  expect(wrapper.text()).toContain('本章：统一冷光')
  expect(wrapper.text()).not.toContain('42')
})
