import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import AgentUsageDetails from './AgentUsageDetails.vue'

it('distinguishes missing cache usage from a reported zero and keeps details collapsed', () => {
  const wrapper = mount(AgentUsageDetails, { props: { usage: { requests: 2, input_tokens: 1000, output_tokens: 50, cache_read_tokens: 800, cache_usage_reported: true, cache_price_configured: false } } })
  expect(wrapper.text()).toContain('80.0%')
  expect(wrapper.text()).not.toContain('尚未配置缓存输入单价')
  expect(wrapper.get('button[aria-expanded]').attributes('aria-expanded')).toBe('false')
  expect(wrapper.get('.agent-disclosure__collapse').attributes('inert')).toBeDefined()
  const missing = mount(AgentUsageDetails, { props: { usage: { requests: 1 } } })
  expect(missing.text()).not.toContain('输入缓存命中')
  expect(missing.text()).not.toContain('0 / 0 token')
  const zero = mount(AgentUsageDetails, { props: { usage: { requests: 1, input_tokens: 100, cache_usage_reported: true } } })
  expect(zero.text()).toContain('0.0%')
})

it('shows scoped saved rules without exposing internal identifiers', () => {
  const wrapper = mount(AgentUsageDetails, { props: { usage: { remembered_rules: [{ content: '统一冷光', scope: { kind: 'chapter', chapter_id: 42 } }] } } })
  expect(wrapper.text()).toContain('本章：统一冷光')
  expect(wrapper.text()).not.toContain('42')
})

it.each(['light', 'dark'])('shows integer K/M with exact hover values without explanatory warnings (%s)', async theme => {
  document.documentElement.dataset.theme = theme
  const wrapper = mount(AgentUsageDetails, { props: { usage: {
    requests: 9, input_tokens: 438265, output_tokens: 5368, cache_read_tokens: 310920, cache_usage_reported: true,
  } } })
  await wrapper.get('button[aria-expanded]').trigger('click')
  expect(wrapper.text()).toContain('438K / 5K token')
  expect(wrapper.text()).toContain('311K / 127K token')
  expect(wrapper.text()).toContain('70.9%')
  expect(wrapper.get('dd[title]').attributes('title')).toBe('438,265 / 5,368 token')
  expect(wrapper.text()).not.toContain('1K = 1,000 token')
  await wrapper.setProps({ usage: { requests: 1, input_tokens: 2000000, output_tokens: 999, cache_usage_reported: false, missing_usage: true } })
  expect(wrapper.text()).toContain('2M / 999 token')
  expect(wrapper.text()).not.toContain('供应商未完整报告')
  expect(wrapper.text()).not.toContain('部分请求未返回完整用量')
  wrapper.unmount()
  delete document.documentElement.dataset.theme
})
