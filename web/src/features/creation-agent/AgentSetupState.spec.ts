import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/features/auth/authStore'
import AgentSetupState from './AgentSetupState.vue'
import { agentApi } from './api'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('./api', () => ({ agentApi: { configuration: vi.fn(), updateConfiguration: vi.fn() } }))
const capabilities = { enabled: false, can_write: true, max_targets: 8, models: [] }
beforeEach(() => vi.clearAllMocks())

it('enables through the existing configuration endpoint and preserves all limits', async () => {
  const pinia = createPinia()
  useAuthStore(pinia).enabled = false
  const config = { enabled: false, request_limit: 6, tool_calls_limit: 8, max_targets: 8, timeout_seconds: 180, max_context_characters: 28000, history_runs: 6, max_output_tokens: 3000, total_tokens_limit: 30000 }
  vi.mocked(agentApi.configuration).mockResolvedValue({ code: 0, message: '', data: config })
  vi.mocked(agentApi.updateConfiguration).mockResolvedValue({ code: 0, message: '', data: { ...config, enabled: true } })
  const wrapper = mount(AgentSetupState, { props: { capabilities, loading: false, error: '' }, global: { plugins: [pinia] } })
  await wrapper.findAll('button').find(button => button.text() === '启用创作助手')!.trigger('click')
  await flushPromises()
  expect(agentApi.updateConfiguration).toHaveBeenCalledWith({ ...config, enabled: true })
  expect(wrapper.emitted('retry')).toHaveLength(1)
  wrapper.unmount()
})

it('does not offer global configuration to an ordinary creator', () => {
  const pinia = createPinia()
  useAuthStore(pinia).enabled = true
  const wrapper = mount(AgentSetupState, { props: { capabilities, loading: false, error: '' }, global: { plugins: [pinia] } })
  expect(wrapper.text()).toContain('联系管理员')
  expect(wrapper.findAll('button').some(button => button.text() === '启用创作助手')).toBe(false)
  expect(agentApi.configuration).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('distinguishes a connection failure from a disabled assistant', () => {
  const wrapper = mount(AgentSetupState, { props: { capabilities: null, loading: false, error: '网络超时' }, global: { plugins: [createPinia()] } })
  expect(wrapper.text()).toContain('暂时无法连接')
  expect(wrapper.text()).not.toContain('尚未启用')
  expect(wrapper.get('[role="alert"]').text()).toBe('网络超时')
  wrapper.unmount()
})
