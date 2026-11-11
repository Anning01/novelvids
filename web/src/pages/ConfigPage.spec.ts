import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import AppButton from '@/components/AppButton.vue'
import AppMultiSelect from '@/components/AppMultiSelect.vue'
import AppSelect from '@/components/AppSelect.vue'
import ConfigPage from './ConfigPage.vue'
import { api } from '@/api'
import { useAuthStore } from '@/features/auth/authStore'
import { notice } from '@/shared/notice'

vi.mock('@/shared/notice', () => ({ notice: { success: vi.fn(), error: vi.fn() } }))

function baseMocks() {
  vi.spyOn(api, 'enums').mockResolvedValue({
    data: {
      ai_task_type: [{ value: 1, label: '内容理解' }],
      image_model_type: [],
      video_model_type: [],
    },
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

it.each(['light', 'dark'])('GPT Image 型号按 1K/2K/4K 分辨率计价，并保留自定义渠道（%s）', async theme => {
  document.documentElement.dataset.appTheme = theme
  baseMocks()
  const models = ['gpt_image_2', 'gpt_image_2_5', 'gpt_image_2_6', 'gpt_image_2_6_sunburst', 'gpt_image_2_6_flare']
  vi.mocked(api.enums).mockResolvedValue({ data: { ai_task_type: [{ value: 2, label: '参考图' }],
    image_model_type: models.map(value => ({ value, label: value })), video_model_type: [] } } as never)
  vi.mocked(api.generationCapabilities).mockResolvedValue({ data: { image: Object.fromEntries(models.map(model => [model, ['1K', '2K', '4K']])),
    image_protocols: { ...Object.fromEntries(models.map(model => [model, ['openai_compatible']])),
      seedream_5_lite: ['volcengine_ark', 'openrouter_compatible'] }, video: {} } } as never)
  vi.spyOn(api, 'configs').mockResolvedValue({ data: { items: [] } } as never)
  let rejectSave: (error: Error) => void = () => {}
  const create = vi.spyOn(api, 'createConfig').mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectSave = reject }))
    .mockResolvedValue({ data: {} } as never)
  const wrapper = mountPage(createPinia())
  await flushPromises()
  await wrapper.get('.model-category-card.is-image').trigger('click')
  expect(wrapper.find('.model-empty-state').exists()).toBe(true)
  await wrapper.get('.model-config-section header button').trigger('click')
  await wrapper.get('input[name="model-config-name"]').setValue('我的生图渠道')
  await wrapper.get('input[name="model-service-base-url"]').setValue('https://custom.example/proxy/v1')
  await wrapper.get('input[name="model-service-api-key"]').setValue('test-key')
  await wrapper.get('input[name="model-id"]').setValue('supplier-model-alias')
  const modelSelect = wrapper.findAllComponents(AppSelect).find(item => item.props('ariaLabel') === '生图模型类型')!
  for (const model of models) {
    modelSelect.vm.$emit('update:modelValue', model)
    await flushPromises()
    expect(wrapper.findAll('.pricing-editor .pricing-grid label').slice(0, 3).map(label => label.text())).toEqual(['清晰度 1K', '清晰度 2K', '清晰度 4K'])
    const protocol = wrapper.findAllComponents(AppSelect).find(item => item.props('ariaLabel') === '接口协议')!
    expect(protocol.props('modelValue')).toBe('openai_compatible')
    expect(protocol.props('options')).toHaveLength(1)
  }
  modelSelect.vm.$emit('update:modelValue', 'seedream_5_lite')
  await flushPromises()
  expect(wrapper.findAllComponents(AppSelect).find(item => item.props('ariaLabel') === '接口协议')!.props('modelValue')).toBe('volcengine_ark')
  modelSelect.vm.$emit('update:modelValue', 'gpt_image_2_6_flare')
  await flushPromises()
  await wrapper.get('form.model-modal').trigger('submit')
  expect(create).not.toHaveBeenCalled()
  expect(notice.error).toHaveBeenCalledWith('请配置全部清晰度档位的输出图单价')
  for (const [index, price] of [0.06, 0.08, 0.16].entries()) {
    await wrapper.findAll('.pricing-editor .pricing-grid label').at(index)!.get('input').setValue(price)
  }
  await modelSelect.get('button').trigger('mouseenter')
  await modelSelect.get('button').trigger('focus')
  await modelSelect.get('button').trigger('keydown', { key: 'ArrowDown' })
  expect(document.querySelector('[role="listbox"][aria-label="生图模型类型"]')).not.toBeNull()
  await modelSelect.get('button').trigger('keydown', { key: 'Escape' })
  await wrapper.get('form.model-modal').trigger('submit')
  expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()
  expect(wrapper.get('button[type="submit"]').attributes('aria-busy')).toBe('true')
  rejectSave(new Error('渠道保存失败'))
  await flushPromises()
  expect(notice.error).toHaveBeenCalledWith('渠道保存失败')
  expect(wrapper.find('form.model-modal').exists()).toBe(true)
  expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeUndefined()
  await wrapper.get('form.model-modal').trigger('submit')
  await flushPromises()
  expect(create).toHaveBeenLastCalledWith(expect.objectContaining({ image_model_type: 'gpt_image_2_6_flare',
    base_url: 'https://custom.example/proxy/v1', model: 'supplier-model-alias', api_protocol: 'openai_compatible',
    pricing: expect.objectContaining({ prices: { '1K': 0.06, '2K': 0.08, '4K': 0.16 } }) }))
  expect(wrapper.find('form.model-modal').exists()).toBe(false)
  wrapper.unmount()
  delete document.documentElement.dataset.appTheme
})

it.each(['light', 'dark'])('旧质量单价需要手动填写分辨率单价，不自动换算（%s）', async theme => {
  document.documentElement.dataset.appTheme = theme
  baseMocks()
  vi.mocked(api.generationCapabilities).mockResolvedValue({ data: { image: { gpt_image_2: ['1K', '2K', '4K'] },
    image_protocols: { gpt_image_2: ['openai_compatible'] }, video: {} } } as never)
  vi.spyOn(api, 'configs').mockResolvedValue({ data: { items: [{ id: 12, name: 'GPT Image 2', task_type: 2,
    task_types: [2], image_model_type: 'gpt_image_2', model: 'gpt-image-2', api_protocol: 'openai_compatible',
    base_url: 'https://custom.example/v1', api_key: 'test', is_active: true, concurrency: 1,
    pricing: { type: 'image', prices: { low: 0.06, medium: 0.08, high: 0.16 } } }] } } as never)
  const update = vi.spyOn(api, 'updateConfig').mockResolvedValue({ data: {} } as never)
  const wrapper = mountPage(createPinia())
  await flushPromises()
  await wrapper.get('.model-category-card.is-image').trigger('click')
  await wrapper.get('[aria-label="编辑配置"]').trigger('click')
  const prices = wrapper.findAll('.pricing-editor .pricing-grid label').slice(0, 3)
  expect(prices.map(item => item.text())).toEqual(['清晰度 1K', '清晰度 2K', '清晰度 4K'])
  expect(prices.map(item => item.get<HTMLInputElement>('input').element.value)).toEqual(['', '', ''])
  await wrapper.get('form.model-modal').trigger('submit')
  expect(update).not.toHaveBeenCalled()
  expect(notice.error).toHaveBeenCalledWith('请配置全部清晰度档位的输出图单价')
  for (const [index, price] of [0, 0.2, 0.4].entries()) await prices[index]!.get('input').setValue(price)
  await wrapper.get('form.model-modal').trigger('submit')
  await flushPromises()
  expect(update).toHaveBeenCalledWith(12, expect.objectContaining({
    pricing: expect.objectContaining({ prices: { '1K': 0, '2K': 0.2, '4K': 0.4 } }),
  }))
  wrapper.unmount()
  delete document.documentElement.dataset.appTheme
})

describe('ConfigPage 平台配置仅超管可见', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it.each(['light', 'dark'])('配置卡片隐藏服务来源，地址仅在编辑表单中显示并保留（%s）', async theme => {
    document.documentElement.dataset.appTheme = theme
    baseMocks()
    const baseUrl = 'https://private-gateway.example.test/internal/v1'
    const categories = [
      { id: 'llm', task: 1 }, { id: 'image', task: 2 }, { id: 'video', task: 4 },
      { id: 'enhancement', task: 8 }, { id: 'asr', task: 9 },
    ]
    const items = categories.map((category, index) => ({
      id: index + 1, name: `配置 ${category.id}`, task_type: category.task, task_types: [category.task],
      model: 'configured-model', base_url: baseUrl, api_key: 'test-only-key', api_protocol: 'unified_video',
      video_model_type: category.id === 'video' ? 'seedance_2_5' : null,
      is_active: index % 2 === 0, concurrency: 10, scope: 'official',
    }))
    vi.spyOn(api, 'configs').mockResolvedValue({ data: { items } } as never)
    const update = vi.spyOn(api, 'updateConfig').mockResolvedValue({ data: {} } as never)
    const wrapper = mountPage(createPinia())
    await flushPromises()
    for (const category of categories) {
      await wrapper.get(`.model-category-card.is-${category.id}`).trigger('click')
      const card = wrapper.get('.model-config-card')
      expect(card.text()).toContain(`配置 ${category.id}`)
      expect(card.text()).toContain('configured-model')
      expect(card.html()).not.toContain('private-gateway.example.test')
      expect(card.html()).not.toContain(baseUrl)
      expect(card.html()).not.toContain('test-only-key')
      expect(card.find('.config-metadata .lucide-server').exists()).toBe(false)
    }
    await wrapper.get('.model-category-card.is-video').trigger('click')
    await wrapper.get('[aria-label="编辑配置"]').trigger('click')
    expect(wrapper.get<HTMLInputElement>('input[name="model-service-base-url"]').element.value).toBe(baseUrl)
    await wrapper.get('form.model-modal').trigger('submit')
    await flushPromises()
    expect(update).toHaveBeenCalledWith(3, expect.objectContaining({ base_url: baseUrl, api_key: 'test-only-key' }))
    expect(wrapper.find('form.model-modal').exists()).toBe(false)
    expect(wrapper.get('.model-config-card').html()).not.toContain('private-gateway.example.test')
    wrapper.unmount()
    delete document.documentElement.dataset.appTheme
  })

  it.each(['light', 'dark'])('保留缓存价并独立调整倍率，官方价使用后台配置（%s）', async (theme) => {
    document.documentElement.dataset.theme = theme
    baseMocks()
    vi.mocked(api.generationCapabilities).mockResolvedValue({ data: { image: {}, video: {}, text_pricing: {
      'deepseek-flash': { type: 'text', currency: 'CNY', input_price_per_1m: 2, cache_input_price_per_1m: 0.04, output_price_per_1m: 8 },
    } } } as never)
    vi.spyOn(api, 'configs').mockResolvedValue({ data: { items: [{
      id: 1, name: 'DeepSeek', task_type: 7, task_types: [7], model: 'deepseek-flash', base_url: 'https://test.invalid',
      api_key: 'test', api_protocol: 'openai_compatible', concurrency: 1, is_active: false,
      pricing: { type: 'text', currency: 'CNY', input_price_per_1m: 12, output_price_per_1m: 24, cache_input_price_per_1m: 0.15, discount: 1.5 },
    }], pagination: { total: 1, page: 1, page_size: 100, pages: 1 } } } as never)
    const update = vi.spyOn(api, 'updateConfig').mockResolvedValue({ data: {} } as never)
    const wrapper = mountPage(createPinia())
    await flushPromises()
    await wrapper.get('[aria-label="编辑配置"]').trigger('click')
    const cache = wrapper.get<HTMLInputElement>('[aria-describedby="cache-price-hint"]')
    expect(cache.element.value).toBe('0.15')
    expect(wrapper.get('#cache-price-hint').text()).toContain('填 0')
    await wrapper.findAll('button').find(button => button.text() === '填入官方基准价')!.trigger('click')
    expect(cache.element.value).toBe('0.04')
    await wrapper.get('form.model-modal').trigger('submit')
    await flushPromises()
    expect(update).toHaveBeenCalledWith(1, expect.objectContaining({ pricing: expect.objectContaining({
      input_price_per_1m: 2, cache_input_price_per_1m: 0.04, output_price_per_1m: 8, discount: 1.5,
    }) }))
    wrapper.unmount()
    delete document.documentElement.dataset.theme
  })

  it.each(['', '0', '0.001'])('任意文本模型保存可选缓存价 %s 并显示失败/加载反馈', async (value) => {
    baseMocks()
    vi.spyOn(api, 'configs').mockResolvedValue({ data: { items: [], pagination: { total: 0, page: 1, page_size: 100, pages: 0 } } } as never)
    let rejectSave: (error: Error) => void = () => {}
    const create = vi.spyOn(api, 'createConfig').mockImplementation(() => new Promise((_resolve, reject) => { rejectSave = reject }))
    const wrapper = mountPage(createPinia())
    await flushPromises()
    await wrapper.get('.model-config-section button').trigger('click')
    await wrapper.get('input[name="model-config-name"]').setValue('Other model')
    await wrapper.get('input[name="model-service-base-url"]').setValue('https://test.invalid')
    await wrapper.get('input[name="model-service-api-key"]').setValue('test')
    await wrapper.get('input[name="model-id"]').setValue('another-provider-model')
    expect(wrapper.text()).not.toContain('填入官方基准价')
    await wrapper.get('[aria-describedby="cache-price-hint"]').setValue(value)
    await wrapper.get('form.model-modal').trigger('submit')
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()
    const saved = create.mock.calls[0]![0].pricing!
    if (value === '') expect(saved).not.toHaveProperty('cache_input_price_per_1m')
    else expect(saved.cache_input_price_per_1m).toBe(Number(value))
    rejectSave(new Error('Save failed'))
    await flushPromises()
    expect(notice.error).toHaveBeenCalledWith('Save failed')
    expect(wrapper.find('form.model-modal').exists()).toBe(true)
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
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
    const videoTypeSelect = wrapper.findAllComponents(AppSelect).find(item => item.props('ariaLabel') === '视频模型类型')
    expect(videoTypeSelect).toBeTruthy()
    videoTypeSelect!.vm.$emit('update:modelValue', 'minimax_h3')
    await flushPromises()

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
  expect(wrapper.text()).not.toContain('本地成片通过MediaKit临时上传读取')
  expect(wrapper.text()).not.toContain('默认价格来自后台能力配置')
  await input.setValue(true); await input.setValue(false); await input.setValue(true)
  await wrapper.get('form.model-modal').trigger('submit'); await flushPromises()
  expect(update).toHaveBeenCalledWith(12, expect.objectContaining({ processing_options: { output_resolutions: ['1080p','2k'] },
    pricing: expect.objectContaining({ tiers: [...rates,...higher] }) }))
  wrapper.unmount()
})

it('模型配置表单统一使用共享选择器组件，不再渲染原生下拉框', async () => {
  baseMocks()
  vi.mocked(api.enums).mockResolvedValue({
    data: {
      ai_task_type: [{ value: 1, label: '内容理解' }],
      image_model_type: [{ value: 'seedream_5_lite', label: 'Doubao Seedream 5.0 Lite' }],
      video_model_type: [{ value: 'minimax_h3', label: 'MiniMax H3' }],
    },
  } as never)
  vi.spyOn(api, 'configs').mockResolvedValue({ data: { items: [] } } as never)

  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mountPage(pinia)
  await flushPromises()

  const openModal = async (category: string) => {
    await wrapper.get(`.model-category-card.is-${category}`).trigger('click')
    await wrapper.get('.model-config-section button').trigger('click')
    await flushPromises()
  }
  const closeModal = async () => {
    await wrapper.get('.model-modal header [aria-label="关闭"]').trigger('click')
    await flushPromises()
  }
  const selectorLabels = () => wrapper.findAllComponents(AppSelect).map(item => item.props('ariaLabel'))

  await openModal('llm')
  expect(wrapper.findAll('form.model-modal select')).toHaveLength(0)
  expect(selectorLabels()).toContain('思考模式')

  await closeModal()
  await openModal('image')
  expect(wrapper.findAll('form.model-modal select')).toHaveLength(0)
  expect(selectorLabels()).toContain('生图模型类型')
  expect(selectorLabels()).toContain('接口协议')

  await closeModal()
  await openModal('video')
  expect(wrapper.findAll('form.model-modal select')).toHaveLength(0)
  expect(selectorLabels()).toContain('视频模型类型')
  wrapper.unmount()
})

it('Esc 关闭模型配置弹窗，展开的下拉菜单优先收起', async () => {
  baseMocks()
  vi.mocked(api.enums).mockResolvedValue({
    data: {
      ai_task_type: [{ value: 2, label: '角色与场景参考图' }],
      image_model_type: [{ value: 'seedream_5_lite', label: 'Doubao Seedream 5.0 Lite' }],
      video_model_type: [],
    },
  } as never)
  vi.spyOn(api, 'configs').mockResolvedValue({ data: { items: [] } } as never)

  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mountPage(pinia)
  await flushPromises()

  await wrapper.get('.model-category-card.is-image').trigger('click')
  await wrapper.get('.model-config-section button').trigger('click')
  await flushPromises()
  expect(wrapper.find('form.model-modal').exists()).toBe(true)

  // 下拉菜单展开时，Esc 只收起菜单，弹窗保持打开
  const imageTypeSelect = wrapper.findAllComponents(AppSelect).find(item => item.props('ariaLabel') === '生图模型类型')!
  await imageTypeSelect.get('button').trigger('click')
  await flushPromises()
  expect(document.querySelector('.app-select__menu')).not.toBeNull()
  await imageTypeSelect.get('button').trigger('keydown', { key: 'Escape' })
  await flushPromises()
  expect(document.querySelector('.app-select__menu')).toBeNull()
  expect(wrapper.find('form.model-modal').exists()).toBe(true)

  // 焦点在弹窗内时 Esc 直接关闭弹窗
  await wrapper.get('input[name="model-config-name"]').trigger('keydown', { key: 'Escape' })
  await flushPromises()
  expect(wrapper.find('form.model-modal').exists()).toBe(false)

  // 焦点不在弹窗内时 Esc 同样关闭弹窗
  await wrapper.get('.model-config-section button').trigger('click')
  await flushPromises()
  expect(wrapper.find('form.model-modal').exists()).toBe(true)
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  await flushPromises()
  expect(wrapper.find('form.model-modal').exists()).toBe(false)
  wrapper.unmount()
})

it.each([
  ['image', '生图模型类型', '请选择受支持的模型'],
  ['video', '视频模型类型', '请选择受支持的视频模型'],
] as const)('未选择 %s 模型类型时阻止提交并提示缺少模型类型', async (category, label, message) => {
  baseMocks()
  vi.mocked(api.enums).mockResolvedValue({
    data: {
      ai_task_type: [{ value: 2, label: '角色与场景参考图' }],
      image_model_type: [{ value: 'seedream_5_lite', label: 'Doubao Seedream 5.0 Lite' }],
      video_model_type: [],
    },
  } as never)
  vi.spyOn(api, 'configs').mockResolvedValue({ data: { items: [] } } as never)
  const createConfig = vi.spyOn(api, 'createConfig').mockResolvedValue({ data: {} } as never)

  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mountPage(pinia)
  await flushPromises()

  await wrapper.get(`.model-category-card.is-${category}`).trigger('click')
  await wrapper.get('.model-config-section button').trigger('click')
  await flushPromises()

  const typeSelect = wrapper.findAllComponents(AppSelect).find(item => item.props('ariaLabel') === label)
  expect(typeSelect).toBeTruthy()
  typeSelect!.vm.$emit('update:modelValue', '')
  await flushPromises()

  await wrapper.get('input[name="model-config-name"]').setValue('缺少模型类型')
  await wrapper.get('form.model-modal').trigger('submit')
  await flushPromises()

  expect(createConfig).not.toHaveBeenCalled()
  expect(notice.error).toHaveBeenCalledWith(message)
  wrapper.unmount()
})

it.each(['light', 'dark'])('selects a video model from the shared popup and submits its preset (%s)', async theme => {
  document.documentElement.dataset.appTheme = theme
  baseMocks()
  vi.mocked(api.enums).mockResolvedValue({ data: {
    ai_task_type: [{ value: 4, label: '视频片段生成' }], image_model_type: [],
    video_model_type: [{ value: 'seedance_2', label: 'Doubao Seedance 2.0' }, { value: 'minimax_h3', label: 'MiniMax H3' }],
  } } as never)
  vi.spyOn(api, 'configs').mockResolvedValue({ data: { items: [] } } as never)
  const createConfig = vi.spyOn(api, 'createConfig').mockResolvedValue({ data: {} } as never)
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mountPage(pinia)
  await flushPromises()
  await wrapper.get('.model-category-card.is-video').trigger('click')
  await wrapper.get('.model-config-section button').trigger('click')
  await wrapper.get('button[aria-label="视频模型类型"]').trigger('click')
  await flushPromises()
  const menu = document.querySelector<HTMLElement>('[role="listbox"][aria-label="视频模型类型"]')!
  expect(menu.style.zIndex).toBe('2000')
  const option = [...menu.querySelectorAll<HTMLButtonElement>('[role="option"]')].find(item => item.textContent?.trim() === 'MiniMax H3')!
  option.click()
  await flushPromises()
  expect(wrapper.get('button[aria-label="视频模型类型"]').text()).toBe('MiniMax H3')
  expect(document.querySelector('[role="listbox"][aria-label="视频模型类型"]')).toBeNull()
  await wrapper.get('input[name="model-config-name"]').setValue('Video model')
  await wrapper.get('input[name="model-service-api-key"]').setValue('test-only-key')
  await wrapper.get('form.model-modal').trigger('submit')
  await flushPromises()
  expect(createConfig).toHaveBeenCalledWith(expect.objectContaining({ video_model_type: 'minimax_h3', base_url: 'https://api.minimaxi.com', model: 'MiniMax-H3', api_protocol: 'minimax' }))
  wrapper.unmount()
})

it.each(['light', 'dark'])('selects AutoDL from the shared popup and submits its workflow (%s)', async theme => {
  document.documentElement.dataset.appTheme = theme
  baseMocks()
  vi.mocked(api.enums).mockResolvedValue({ data: {
    ai_task_type: [{ value: 4, label: '视频片段生成' }], image_model_type: [],
    video_model_type: [{ value: 'seedance_2', label: 'Doubao Seedance 2.0' }, { value: 'minimax_h3_autodl', label: 'MiniMax H3 · AutoDL' }],
  } } as never)
  vi.spyOn(api, 'configs').mockResolvedValue({ data: { items: [] } } as never)
  const createConfig = vi.spyOn(api, 'createConfig').mockResolvedValue({ data: {} } as never)
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mountPage(pinia)
  await flushPromises()
  await wrapper.get('.model-category-card.is-video').trigger('click')
  await wrapper.get('.model-config-section button').trigger('click')
  await wrapper.get('button[aria-label="视频模型类型"]').trigger('click')
  await flushPromises()
  const menu = document.querySelector<HTMLElement>('[role="listbox"][aria-label="视频模型类型"]')!
  expect(menu.style.zIndex).toBe('2000')
  const option = [...menu.querySelectorAll<HTMLButtonElement>('[role="option"]')].find(item => item.textContent?.trim() === 'MiniMax H3 · AutoDL')!
  option.click()
  await flushPromises()
  expect(wrapper.get('button[aria-label="视频模型类型"]').text()).toBe('MiniMax H3 · AutoDL')
  expect(document.querySelector('[role="listbox"][aria-label="视频模型类型"]')).toBeNull()
  await wrapper.get('input[name="model-config-name"]').setValue('Video model')
  await wrapper.get('input[name="model-service-api-key"]').setValue('test-only-key')
  await wrapper.get('form.model-modal').trigger('submit')
  await flushPromises()
  expect(createConfig).toHaveBeenCalledWith(expect.objectContaining({ video_model_type: 'minimax_h3_autodl', base_url: 'https://autodl.art/api/v1/comfyui', model: 'minimax_h3_zm_u24', api_protocol: 'autodl' }))
  wrapper.unmount()
})

it.each(['light', 'dark'])('配置通用视频协议，保留编辑值并显示加载、失败和成功状态（%s）', async theme => {
  document.documentElement.dataset.appTheme = theme
  baseMocks()
  vi.mocked(api.enums).mockResolvedValue({ data: {
    ai_task_type: [{ value: 4, label: '视频片段生成' }], image_model_type: [],
    video_model_type: [{ value: 'seedance_2', label: 'Doubao Seedance 2.0' }],
  } } as never)
  vi.mocked(api.generationCapabilities).mockResolvedValue({ data: { image: {},
    video: { seedance_2: ['480p', '720p', '1080p', '4k'] },
    video_protocols: { seedance_2: [
      { value: 'volcengine_ark', label: '火山方舟', resolutions: ['480p', '720p', '1080p', '4k'] },
      { value: 'unified_video', label: '通用视频接口', resolutions: ['480p', '720p', '1080p'] },
    ] },
  } } as never)
  vi.spyOn(api, 'configs').mockResolvedValue({ data: { items: [] } } as never)
  let rejectSave: (error: Error) => void = () => {}
  const create = vi.spyOn(api, 'createConfig').mockImplementation(() => new Promise((_resolve, reject) => { rejectSave = reject }))
  const update = vi.spyOn(api, 'updateConfig').mockResolvedValue({ data: {} } as never)
  const wrapper = mountPage(createPinia())
  await flushPromises()
  await wrapper.get('.model-category-card.is-video').trigger('click')
  expect(wrapper.find('.model-empty-state').exists()).toBe(true)
  await wrapper.get('.model-config-section button').trigger('click')
  const protocol = wrapper.get('button[aria-label="视频接口协议"]')
  await protocol.trigger('focus')
  await protocol.trigger('keydown', { key: 'ArrowDown' })
  await flushPromises()
  const menu = document.querySelector<HTMLElement>('[role="listbox"][aria-label="视频接口协议"]')!
  expect(menu).not.toBeNull()
  const option = [...menu.querySelectorAll<HTMLButtonElement>('[role="option"]')].find(item => item.textContent?.trim() === '通用视频接口')!
  option.dispatchEvent(new MouseEvent('mouseenter'))
  option.click()
  await flushPromises()
  expect(protocol.text()).toBe('通用视频接口')
  expect(wrapper.text()).not.toContain('4k')
  expect(wrapper.text()).not.toMatch(/渠道|\/contents\/generations\/tasks/i)
  expect(wrapper.get<HTMLInputElement>('input[name="model-service-base-url"]').element.value).toBe('')
  expect(wrapper.get<HTMLInputElement>('input[name="model-id"]').element.value).toBe('')
  await wrapper.get('input[name="model-config-name"]').setValue('视频服务')
  await wrapper.get('input[name="model-service-base-url"]').setValue('https://video.example.test/v1')
  await wrapper.get('input[name="model-id"]').setValue('configured-model')
  await wrapper.get('input[name="model-service-api-key"]').setValue('key')
  await wrapper.get('form.model-modal').trigger('submit')
  expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()
  expect(create).toHaveBeenCalledWith(expect.objectContaining({
    api_protocol: 'unified_video', video_model_type: 'seedance_2', model: 'configured-model',
    base_url: 'https://video.example.test/v1', pricing: expect.objectContaining({ prices: { '480p': 0, '720p': 0, '1080p': 0 } }),
  }))
  rejectSave(new Error('保存失败'))
  await flushPromises()
  expect(notice.error).toHaveBeenCalledWith('保存失败')
  expect(wrapper.find('form.model-modal').exists()).toBe(true)
  create.mockResolvedValueOnce({ data: {} } as never)
  vi.mocked(api.configs).mockResolvedValue({ data: { items: [{ id: 9, ...create.mock.calls[0]![0] }] } } as never)
  await wrapper.get('form.model-modal').trigger('submit')
  await flushPromises()
  expect(wrapper.find('form.model-modal').exists()).toBe(false)
  await wrapper.get('[aria-label="编辑配置"]').trigger('click')
  expect(wrapper.get('button[aria-label="视频接口协议"]').text()).toBe('通用视频接口')
  expect(wrapper.get<HTMLInputElement>('input[name="model-service-base-url"]').element.value).toBe('https://video.example.test/v1')
  await wrapper.get('form.model-modal').trigger('submit')
  await flushPromises()
  expect(update).toHaveBeenCalledWith(9, expect.objectContaining({ api_protocol: 'unified_video' }))
  wrapper.unmount()
  delete document.documentElement.dataset.appTheme
})

it.each(['light', 'dark'])('只展示模型配置，不加载旧通用配置（%s）', async theme => {
  document.documentElement.dataset.appTheme = theme
  baseMocks()
  vi.spyOn(api, 'configs').mockResolvedValue({ data: { items: [] } } as never)
  const generalConfig = vi.spyOn(api, 'generalConfig')
  const wrapper = mountPage(teamAdminStore())
  await flushPromises()

  expect(wrapper.get('h1').text()).toBe('模型配置')
  expect(wrapper.find('.model-category-grid').exists()).toBe(true)
  expect(wrapper.find('.model-config-section').exists()).toBe(true)
  expect(wrapper.find('.settings-section-tabs').exists()).toBe(false)
  expect(wrapper.find('.general-settings-section').exists()).toBe(false)
  expect(wrapper.text()).not.toContain('通用配置')
  expect(wrapper.text()).not.toContain('创作偏好')
  expect(generalConfig).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('creates ASR configuration with server-provided defaults and minute pricing',async()=>{
  baseMocks()
  vi.mocked(api.generationCapabilities).mockResolvedValue({data:{image:{},video:{},audio_recognition:{base_url:'https://openspeech.bytedance.com/api/v3/auc/bigmodel',model:'volc.seedasr.auc',api_protocol:'volcengine_openspeech',pricing:{type:'asr',currency:'CNY',billing_unit:'minute',price_per_minute:.031}}}} as never)
  vi.spyOn(api,'configs').mockResolvedValue({data:{items:[]}} as never)
  const create=vi.spyOn(api,'createConfig').mockResolvedValue({data:{}} as never)
  const wrapper=mountPage(teamAdminStore());await flushPromises()
  await wrapper.findAll('.model-category-card').find(card=>card.text().includes('语音识别'))!.trigger('click')
  await wrapper.get('.model-config-section > header button').trigger('click')
  await wrapper.get('input[name="model-config-name"]').setValue('ASR test')
  await wrapper.get('input[name="model-service-api-key"]').setValue('test-key')
  expect((wrapper.get('[aria-label="ASR price per minute"]').element as HTMLInputElement).value).toBe('0.031')
  await wrapper.get('form.model-modal').trigger('submit');await flushPromises()
  expect(create).toHaveBeenCalledWith(expect.objectContaining({task_type:9,model:'volc.seedasr.auc',api_protocol:'volcengine_openspeech',pricing:expect.objectContaining({type:'asr',price_per_minute:.031,billing_unit:'minute'})}))
  wrapper.unmount()
})
