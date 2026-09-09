import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import AgentSettingsPanel from './AgentSettingsPanel.vue'
import { agentApi } from './api'
import type { AgentConfiguration } from './types'

vi.mock('./api', () => ({ agentApi: { configuration: vi.fn(), updateConfiguration: vi.fn() } }))
const configuration: AgentConfiguration = { enabled: false, request_limit: 6, tool_calls_limit: 8, max_targets: 8,
  timeout_seconds: 180, max_context_characters: 28000, history_runs: 6, max_output_tokens: 3000, total_tokens_limit: 30000 }

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(agentApi.configuration).mockResolvedValue({ code: 0, message: '', data: { ...configuration } })
  vi.mocked(agentApi.updateConfiguration).mockImplementation(async value => ({ code: 0, message: '', data: value }))
})

it('keeps assistant activation and budgets backend managed', async () => {
  const wrapper = mount(AgentSettingsPanel)
  await flushPromises()
  const enabled = wrapper.get('input[role="switch"]')
  await enabled.setValue(true)
  await wrapper.get('form').trigger('submit')
  expect(agentApi.updateConfiguration).toHaveBeenCalledWith(expect.objectContaining({ enabled: true, request_limit: 6, max_targets: 8 }))
})

it('shows a stable error when global settings are unavailable', async () => {
  vi.mocked(agentApi.configuration).mockRejectedValue(new Error('仅超级管理员可执行此操作'))
  const wrapper = mount(AgentSettingsPanel)
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('仅超级管理员')
  expect(wrapper.find('form').exists()).toBe(false)
})
