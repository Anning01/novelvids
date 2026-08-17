import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import AppButton from '@/components/AppButton.vue'
import ConfigPage from './ConfigPage.vue'
import { api } from '@/api'
import { useAuthStore } from '@/features/auth/authStore'

function baseMocks() {
  vi.spyOn(api, 'configs').mockResolvedValue({
    data: {
      items: [
        { id: 1, name: '官方文本模型', scope: 'official', team_id: null, task_type: 1, task_types: [1, 3, 5], base_url: 'https://x/v1', api_key: null, model: 'm1', api_protocol: 'openai_compatible', is_active: true, concurrency: 1, supports_json_output: true, created_at: '', updated_at: '' },
        { id: 2, name: '团队自建模型', scope: 'team', team_id: 9, task_type: 1, task_types: [1], base_url: 'https://y/v1', api_key: 'k', model: 'm2', api_protocol: 'openai_compatible', is_active: false, concurrency: 1, supports_json_output: false, created_at: '', updated_at: '' },
      ],
      pagination: { total: 2, page: 1, page_size: 100, pages: 1 },
    },
  } as never)
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
  vi.spyOn(api, 'modelSource').mockResolvedValue({ data: { source: 'official' } } as never)
  vi.spyOn(api, 'setModelSource').mockResolvedValue({ data: { source: 'custom' } } as never)
}

function mountPage(pinia: Pinia) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/settings', component: ConfigPage }],
  })
  return mount(ConfigPage, { global: { plugins: [pinia, router], components: { AppButton } } })
}

describe('ConfigPage 团队管理员只读官方配置', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('官方配置显示只读徽章且无删除按钮，团队配置可管理', async () => {
    baseMocks()
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

    const wrapper = mountPage(pinia)
    await flushPromises()

    expect(wrapper.text()).toContain('当前模型来源：官方配置')
    expect(wrapper.text()).toContain('官方配置 · 只读')
    // 两张卡片：官方卡没有删除按钮，团队卡有
    const cards = wrapper.findAll('.model-config-card')
    expect(cards).toHaveLength(2)
    expect(cards[0].find('[aria-label="删除配置"]').exists()).toBe(false)
    expect(cards[0].find('.official-badge').exists()).toBe(true)
    expect(cards[1].find('[aria-label="删除配置"]').exists()).toBe(true)
    expect(cards[1].find('.official-badge').exists()).toBe(false)
  })

  it('切换为团队自定义调用后端并更新横幅', async () => {
    baseMocks()
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

    const wrapper = mountPage(pinia)
    await flushPromises()

    const toggle = wrapper.findAll('button').find(button => button.text().includes('切换为团队自定义'))
    expect(toggle).toBeTruthy()
    await toggle!.trigger('click')
    await flushPromises()
    expect(api.setModelSource).toHaveBeenCalledWith('custom')
    expect(wrapper.text()).toContain('团队自定义模式')
  })

  it('超管不受只读限制（不显示官方徽章与模式横幅）', async () => {
    baseMocks()
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
    expect(cards[0].find('.official-badge').exists()).toBe(false)
    expect(cards[0].find('[aria-label="删除配置"]').exists()).toBe(true)
  })
})
