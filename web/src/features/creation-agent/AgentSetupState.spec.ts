import { createPinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/features/auth/authStore'
import AgentSetupState from './AgentSetupState.vue'
import { agentApi } from './api'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('./api', () => ({ agentApi: { configuration: vi.fn(), updateConfiguration: vi.fn() } }))
const capabilities = { enabled: false, can_write: true, max_targets: 8, models: [] }
beforeEach(() => vi.clearAllMocks())

it('links administrators with no assistant model to model settings', () => {
  const pinia = createPinia()
  useAuthStore(pinia).enabled = false
  const wrapper = mount(AgentSetupState, { props: { capabilities, loading: false, error: '' }, global: { plugins: [pinia] } })
  expect(wrapper.text()).toContain('前往模型设置')
  expect(wrapper.text()).not.toContain('启用创作助手')
})

it('does not offer global configuration to an ordinary creator', () => {
  const pinia = createPinia()
  useAuthStore(pinia).enabled = true
  const wrapper = mount(AgentSetupState, { props: { capabilities, loading: false, error: '' }, global: { plugins: [pinia] } })
  expect(wrapper.text()).toContain('还需要配置一个对话模型')
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
