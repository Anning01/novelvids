import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import AppButton from '@/components/AppButton.vue'
import AppMultiSelect from '@/components/AppMultiSelect.vue'
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

  it('creates MediaKit processing configuration with server-provided minute prices', async () => {
    baseMocks()
    vi.mocked(api.generationCapabilities).mockResolvedValue({ data: { image: {}, video: {}, media_processing: {
      base_url: 'https://mediakit.cn-beijing.volces.com', model: 'enhance-video-generative', api_protocol: 'volcengine_mediakit',
      processing_options: { poll_seconds: 15, input_short_side_min: 360 },
      pricing: { type: 'media_processing', currency: 'CNY', billing_unit: 'minute', tiers: [
        { short_side_max: 1080, fps_max: 30, price: 5 }, { short_side_max: 1080, fps_max: 60, price: 10 },
        { short_side_max: 1080, fps_max: 120, price: 20 },
      ] },
    } } } as never)
    vi.spyOn(api, 'configs').mockResolvedValue({ data: { items: [] } } as never)
    const createConfig = vi.spyOn(api, 'createConfig').mockResolvedValue({ data: {} } as never)
    const wrapper = mountPage(teamAdminStore())
    await flushPromises()
    await wrapper.get('.model-category-card.is-enhancement').trigger('click')
    await wrapper.get('.model-config-section > header button').trigger('click')
    expect((wrapper.get('input[name="model-service-base-url"]').element as HTMLInputElement).value).toBe('https://mediakit.cn-beijing.volces.com')
    expect(wrapper.text()).toContain('增强费用（元 / 输出分钟）')
    await wrapper.get('input[name="model-config-name"]').setValue('团队画质增强')
    await wrapper.get('input[name="model-service-api-key"]').setValue('test-only-key')
    await wrapper.get('form.model-modal').trigger('submit')
    await flushPromises()
    expect(createConfig).toHaveBeenCalledWith(expect.objectContaining({
      task_type: 8, task_types: [8], api_protocol: 'volcengine_mediakit', model: 'enhance-video-generative',
      processing_options: expect.objectContaining({ poll_seconds: 15 }),
      pricing: expect.objectContaining({ type: 'media_processing', billing_unit: 'minute', tiers: expect.arrayContaining([
        { short_side_max: 1080, fps_max: 30, price: 5 },
      ]) }),
    }))
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

  it('将重制拆解作为可选择的 LLM 能力用途保存', async () => {
    baseMocks()
    vi.mocked(api.enums).mockResolvedValue({
      data: {
        ai_task_type: [
          { value: 1, label: '提取任务' },
          { value: 3, label: '生成分镜' },
          { value: 5, label: '项目分析' },
          { value: 6, label: '重制' },
        ],
        image_model_type: [],
        video_model_type: [],
      },
    } as never)
    vi.spyOn(api, 'configs').mockResolvedValue({
      data: { items: [], pagination: { total: 0, page: 1, page_size: 100, pages: 0 } },
    } as never)
    const createConfig = vi.spyOn(api, 'createConfig').mockResolvedValue({ data: {} } as never)

    const pinia = createPinia()
    setActivePinia(pinia)
    const wrapper = mountPage(pinia)
    await flushPromises()

    await wrapper.get('.model-config-section button').trigger('click')
    const capabilitySelect = wrapper.getComponent(AppMultiSelect)
    expect(capabilitySelect.props('options')).toContainEqual({ value: '6', label: '重制' })
    capabilitySelect.vm.$emit('update:modelValue', ['1', '6'])
    await wrapper.get('input[name="model-config-name"]').setValue('重制理解模型')
    await wrapper.get('input[name="model-service-base-url"]').setValue('https://model.example.com/v1')
    await wrapper.get('input[name="model-service-api-key"]').setValue('test-key')
    await wrapper.get('input[name="model-id"]').setValue('remake-model')
    await wrapper.get('form.model-modal').trigger('submit')
    await flushPromises()

    expect(createConfig).toHaveBeenCalledWith(expect.objectContaining({
      task_type: 1,
      task_types: [1, 6],
    }))
  })

  it('选择 MiniMax H3 时填入官方端点、模型名和协议', async () => {
    baseMocks()
    vi.mocked(api.enums).mockResolvedValue({
      data: {
        ai_task_type: [{ value: 4, label: '视频生成' }],
        image_model_type: [],
        video_model_type: [
          { value: 'seedance_2', name: 'seedance_2', label: 'Doubao Seedance 2.0' },
          { value: 'minimax_h3', name: 'minimax_h3', label: 'MiniMax H3' },
        ],
      },
    } as never)
    vi.mocked(api.generationCapabilities).mockResolvedValue({
      data: {
        image: {},
        video: { seedance_2: ['720p'], minimax_h3: ['768P', '2K'] },
        video_pricing: {
          minimax_h3: {
            type: 'video',
            currency: 'CNY',
            billing_unit: 'second',
            prices: { '768P': 0.5, '2K': 0.8 },
            video_reference_prices: { '768P': 0.5, '2K': 0.8 },
            input_image: { first_free: 5, price_per_image: 0.2 },
          },
        },
      },
    } as never)
    vi.spyOn(api, 'configs').mockResolvedValue({
      data: { items: [], pagination: { total: 0, page: 1, page_size: 100, pages: 0 } },
    } as never)

    const pinia = createPinia()
    setActivePinia(pinia)
    const wrapper = mountPage(pinia)
    await flushPromises()

    await wrapper.get('.model-category-card.is-video').trigger('click')
    await wrapper.get('.model-config-section button').trigger('click')
    await wrapper.get('select[name="video-model-type"]').setValue('minimax_h3')

    expect((wrapper.get('input[name="model-service-base-url"]').element as HTMLInputElement).value).toBe('https://api.minimaxi.com')
    expect((wrapper.get('input[name="model-id"]').element as HTMLInputElement).value).toBe('MiniMax-H3')
    expect(wrapper.get('[aria-label="视频接口协议"]').text()).toBe('MiniMax 官方')
    expect(wrapper.text()).toContain('/v2/video_generation')
    expect(wrapper.text()).toContain('生成视频（元 / 秒）')
    expect(wrapper.text()).toContain('输入音频免费')
    const pricingInputs = wrapper.findAll('.pricing-editor input[type="number"]')
    expect(pricingInputs.some(input => (input.element as HTMLInputElement).value === '0.5')).toBe(true)
    expect(pricingInputs.some(input => (input.element as HTMLInputElement).value === '0.8')).toBe(true)
    expect(pricingInputs.some(input => (input.element as HTMLInputElement).value === '5')).toBe(true)
    expect(pricingInputs.some(input => (input.element as HTMLInputElement).value === '0.2')).toBe(true)
  })
})

it('enables higher output tiers from server presets while preserving existing configured prices', async () => {
  baseMocks()
  const rates = [30, 60, 120].map((fps, index) => ({ short_side_max: 1080, fps_max: fps, price: 7 * 2 ** index }))
  const higher = [30, 60, 120].map((fps, index) => ({ short_side_max: 1440, fps_max: fps, price: 10 * 2 ** index }))
  vi.mocked(api.generationCapabilities).mockResolvedValue({ data: { image: {}, video: {}, media_processing: {
    base_url: 'https://mediakit.example', model: 'enhance-video-generative', api_protocol: 'volcengine_mediakit',
    processing_options: { output_resolutions: ['1080p','2k'] }, resolutions: [{ value: '1080p', short_side: 1080 }, { value: '2k', short_side: 1440 }],
    pricing: { type: 'media_processing', currency: 'CNY', billing_unit: 'minute', tiers: [...rates, ...higher] },
  } } } as never)
  vi.spyOn(api, 'configs').mockResolvedValue({ data: { items: [{ id: 12, name: '增强服务', task_type: 8, task_types: [8],
    scope: 'team', team_id: 9, model: 'enhance-video-generative', base_url: 'https://mediakit.example', api_key: 'test-only', api_protocol: 'volcengine_mediakit',
    concurrency: 1, processing_options: {}, pricing: { type: 'media_processing', currency: 'CNY', billing_unit: 'minute', tiers: rates } }] } } as never)
  const update = vi.spyOn(api, 'updateConfig').mockResolvedValue({ data: {} } as never)
  const wrapper = mountPage(teamAdminStore()); await flushPromises()
  await wrapper.get('.model-category-card.is-enhancement').trigger('click')
  await wrapper.get('[aria-label="编辑配置"]').trigger('click')
  const input = wrapper.findAll('.enhancement-resolution-options label').find(item => item.text() === '2K')!.get('input')
  await input.setValue(true); await input.setValue(false); await input.setValue(true)
  await wrapper.get('form.model-modal').trigger('submit'); await flushPromises()
  expect(update).toHaveBeenCalledWith(12, expect.objectContaining({ processing_options: { output_resolutions: ['1080p','2k'] },
    pricing: expect.objectContaining({ tiers: [...rates,...higher] }) }))
  wrapper.unmount()
})
