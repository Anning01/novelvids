import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import AppButton from '@/components/AppButton.vue'
import ConfigPage from './ConfigPage.vue'
import { api } from '@/api'
import { useAuthStore } from '@/features/auth/authStore'

function baseMocks() {
  vi.spyOn(api, 'enums').mockResolvedValue({
    data: {
      ai_task_type: [{ value: 1, label: '内容理解' }],
      image_model_type: [],
      video_model_type: [],
    },
  } as never)
  vi.spyOn(api, 'generalConfig').mockResolvedValue({
    data: { id: 1, prompt_language: 'zh', created_at: '', updated_at: '' },
  } as never)
  vi.spyOn(api, 'generationCapabilities').mockResolvedValue({
    data: { image: {}, video: {} },
  } as never)
}

function mountPage(pinia: Pinia) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/settings', component: ConfigPage }],
  })
  return mount(ConfigPage, { global: { plugins: [pinia, router], components: { AppButton } } })
}

function teamAdminStore(): Pinia {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useAuthStore(pinia)
  store.$patch({
    enabled: true,
    token: 't',
    user: { id: 1, username: 'admin', nickname: '', avatar_url: '', is_super_admin: false },
    memberships: [{ team_id: 9, team_name: '测试团队', role: 'admin' }],
    activeTeamId: 9,
  })
  return pinia
}

describe('ConfigPage 平台配置仅超管可见', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('团队管理员只看到本团队配置，并提示未配置时使用平台模型', async () => {
    baseMocks()
    vi.spyOn(api, 'configs').mockResolvedValue({
      data: {
        items: [
          { id: 2, name: '团队自建模型', scope: 'team', team_id: 9, task_type: 1, task_types: [1], base_url: 'https://y/v1', api_key: 'team-key', model: 'm2', api_protocol: 'openai_compatible', is_active: false, concurrency: 1, supports_json_output: false, created_at: '', updated_at: '' },
        ],
        pagination: { total: 1, page: 1, page_size: 100, pages: 1 },
      },
    } as never)

    const wrapper = mountPage(teamAdminStore())
    await flushPromises()

    expect(wrapper.text()).toContain('本团队已配置 1 个模型')
    expect(wrapper.text()).toContain('费用从团队余额扣除')
    expect(wrapper.text()).not.toContain('官方文本模型')
    const card = wrapper.find('.model-config-card')
    expect(card.find('[aria-label="删除配置"]').exists()).toBe(true)
  })

  it('未配置团队模型时提示使用平台模型', async () => {
    baseMocks()
    vi.spyOn(api, 'configs').mockResolvedValue({
      data: { items: [], pagination: { total: 0, page: 1, page_size: 100, pages: 0 } },
    } as never)

    const wrapper = mountPage(teamAdminStore())
    await flushPromises()

    expect(wrapper.text()).toContain('尚未配置团队模型')
    expect(wrapper.text()).toContain('费用从团队余额扣除')
  })

  it('超管看到平台/团队配置徽章并可管理', async () => {
    baseMocks()
    vi.spyOn(api, 'configs').mockResolvedValue({
      data: {
        items: [
          { id: 1, name: '官方文本模型', scope: 'official', team_id: null, task_type: 1, task_types: [1, 3, 5], base_url: 'https://x/v1', api_key: 'k', model: 'm1', api_protocol: 'openai_compatible', is_active: true, concurrency: 1, supports_json_output: true, created_at: '', updated_at: '' },
          { id: 2, name: '团队自建模型', scope: 'team', team_id: 9, task_type: 1, task_types: [1], base_url: 'https://y/v1', api_key: 'team-key', model: 'm2', api_protocol: 'openai_compatible', is_active: false, concurrency: 1, supports_json_output: false, created_at: '', updated_at: '' },
        ],
        pagination: { total: 2, page: 1, page_size: 100, pages: 1 },
      },
    } as never)
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useAuthStore(pinia)
    store.$patch({
      enabled: true,
      token: 't',
      user: { id: 9, username: 'boss', nickname: '', avatar_url: '', is_super_admin: true },
      memberships: [],
      activeTeamId: null,
    })

    const wrapper = mountPage(pinia)
    await flushPromises()

    expect(wrapper.find('.model-source-banner').exists()).toBe(false)
    const cards = wrapper.findAll('.model-config-card')
    expect(cards).toHaveLength(2)
    expect(cards[0].text()).toContain('平台配置')
    expect(cards[1].text()).toContain('团队配置')
    expect(cards[0].find('[aria-label="删除配置"]').exists()).toBe(true)
  })
})
