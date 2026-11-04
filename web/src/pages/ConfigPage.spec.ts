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
