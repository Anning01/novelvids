import { flushPromises, mount } from '@vue/test-utils'
import { parse } from '@vue/compiler-sfc'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import { AssetTypeEnum, type Asset, type AssetVariant, type DigitalHuman, type ImageGenerationModel, type PaginationResponse } from '@/types'
import AppButton from './AppButton.vue'
import AssetCreateDialog from './AssetCreateDialog.vue'
import assetDialogSource from './AssetCreateDialog.vue?raw'

vi.mock('@/api', () => ({
  api: {
    imageGenerationModels: vi.fn(),
    digitalHumans: vi.fn(),
    assetLibrary: vi.fn(),
    asset: vi.fn(),
    assetGenerationHistory: vi.fn(),
    assetVariants: vi.fn(),
    createAssetVariant: vi.fn(),
    updateAssetVariant: vi.fn(),
    assignAssetVariantToChapter: vi.fn(),
    deleteAssetVariant: vi.fn(),
    generateAsset: vi.fn(),
    task: vi.fn(),
    upload: vi.fn(),
    restoreAssetGeneration: vi.fn(),
    referencePromptPreview: vi.fn(),
  },
}))

beforeEach(() => {
  vi.mocked(api.assetGenerationHistory).mockResolvedValue({ code: 0, message: 'ok', data: [] })
  vi.mocked(api.assetVariants).mockResolvedValue({ code: 0, message: 'ok', data: [] })
})

const humans: DigitalHuman[] = [
  {
    id: 1,
    country: '荷兰',
    age: 22,
    gender: '女性',
    occupation: '多肉/花卉种植员',
    asset_id: 'human-one',
    image_url: '/media/human-one.png',
    is_active: true,
    created_at: '2026-07-26T00:00:00.000Z',
    updated_at: '2026-07-26T00:00:00.000Z',
  },
  {
    id: 2,
    country: '南非',
    age: 24,
    gender: '女性',
    occupation: '模特',
    asset_id: 'human-two',
    image_url: '/media/human-two.png',
    is_active: true,
    created_at: '2026-07-26T00:00:00.000Z',
    updated_at: '2026-07-26T00:00:00.000Z',
  },
]

const digitalHumanPage: PaginationResponse<DigitalHuman> = {
  code: 0,
  message: 'ok',
  data: {
    items: humans,
    pagination: { total: humans.length, page: 1, page_size: 24, pages: 1 },
  },
}

const editedAsset: Asset = {
  id: 7,
  novel_id: 9,
  asset_type: AssetTypeEnum.PERSON,
  canonical_name: '李火旺',
  description: '被困在诡异溶洞中的少年，性格偏执。',
  base_traits: `**时代基底**: 架空
**脸型**: 清瘦冷硬
**发型**: 黑发粗麻绳束起
**性别**: 男
**年龄**: 中年，约45岁`,
  metadata: {},
  created_at: '2026-07-26T00:00:00.000Z',
  updated_at: '2026-07-26T00:00:00.000Z',
}

function imageModel(id: number, name: string): ImageGenerationModel {
  return {
    config_id: id,
    name,
    model: `model-${id}`,
    model_type: 'gpt_image_2',
    concurrency: 1,
    capabilities: {
      clarities: ['low', 'medium', 'high'],
      aspect_ratios: ['1:1', '3:2', '2:3'],
      output_formats: ['png', 'jpeg', 'webp'],
      generation_counts: [1],
      default_clarity: 'medium',
      default_aspect_ratio: '1:1',
      default_output_format: 'png',
      default_generation_count: 1,
    },
  }
}

it('lists every running image model and hides stopped models', async () => {
  vi.clearAllMocks()
  vi.mocked(api.assetLibrary).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: { items: [], pagination: { total: 0, page: 1, page_size: 24, pages: 0 } },
  })
  vi.mocked(api.imageGenerationModels).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: [imageModel(1, '运行模型 A'), imageModel(2, '运行模型 B')],
  })

  const wrapper = mount(AssetCreateDialog, {
    props: { open: true, kind: 'scene', novelId: 9 },
    global: { components: { AppButton }, stubs: { Teleport: true } },
  })
  await flushPromises()

  await wrapper.get('button[aria-label="选择生图模型"]').trigger('click')
  const options = wrapper.findAll('[role="option"]').map(option => option.text())
  expect(options).toContain('运行模型 A')
  expect(options).toContain('运行模型 B')
  expect(options).not.toContain('停用模型 C')
})

it('keeps the selected library card outline inside the scroll viewport', async () => {
  const style = document.createElement('style')
  style.textContent = parse(assetDialogSource).descriptor.styles.map(block => block.content).join('\n')
  document.head.append(style)

  vi.mocked(api.digitalHumans).mockResolvedValue(digitalHumanPage)
  vi.mocked(api.assetLibrary).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: { items: [], pagination: { total: 0, page: 1, page_size: 24, pages: 0 } },
  })
  vi.mocked(api.imageGenerationModels).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: [],
  })
  vi.mocked(api.asset).mockResolvedValue({ code: 0, message: 'ok', data: editedAsset })
  vi.mocked(api.referencePromptPreview).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: {
      prompt: '任务：完成角色的上半身正面平视特写和该角色的全身三视图。\n\n角色描述：\n时代基底：架空；脸型：清瘦冷硬；发型：黑发粗麻绳束起',
      prompt_language: 'zh',
    },
  })

  const wrapper = mount(AssetCreateDialog, {
    attachTo: document.body,
    props: { open: true, kind: 'character', novelId: 9, asset: editedAsset },
    global: { components: { AppButton }, stubs: { Teleport: true } },
  })
  await flushPromises()

  expect(wrapper.get('textarea').element.value).toContain('上半身正面平视特写')
  expect(wrapper.get('textarea').element.value).not.toContain(editedAsset.description)

  const libraryMode = wrapper.findAll('button').find(button => button.text().includes('从角色库选择'))
  expect(libraryMode).toBeDefined()
  await libraryMode!.trigger('click')
  await wrapper.vm.$nextTick()

  const cards = wrapper.findAll('.asset-library__card')
  expect(cards).toHaveLength(2)
  await cards[1].trigger('click')
  await flushPromises()

  const selectedCard = wrapper.get('.asset-library__card.is-active')
  expect(getComputedStyle(selectedCard.element).boxShadow).toMatch(/^inset 0 0 0 2px/)
  style.remove()
})

it('fills legacy character gender and age from returned traits without another AI request', async () => {
  vi.clearAllMocks()
  vi.mocked(api.digitalHumans).mockResolvedValue(digitalHumanPage)
  vi.mocked(api.assetLibrary).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: { items: [], pagination: { total: 0, page: 1, page_size: 24, pages: 0 } },
  })
  vi.mocked(api.imageGenerationModels).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: [],
  })
  vi.mocked(api.asset).mockResolvedValue({ code: 0, message: 'ok', data: editedAsset })
  vi.mocked(api.referencePromptPreview).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: { prompt: editedAsset.base_traits || '', prompt_language: 'zh' },
  })

  const wrapper = mount(AssetCreateDialog, {
    props: { open: true, kind: 'character', novelId: 9, asset: editedAsset },
    global: { components: { AppButton }, stubs: { Teleport: true } },
  })
  await flushPromises()

  expect(wrapper.get('button[aria-label="选择性别"]').text()).toContain('男')
  expect(wrapper.get('button[aria-label="选择年龄阶段"]').text()).toContain('中年')
  expect(api.asset).toHaveBeenCalledTimes(1)
})

it('shows an existing generated image and closes quickly with Escape', async () => {
  vi.clearAllMocks()
  const assetWithImage = { ...editedAsset, main_image: '/media/generated-character.png' }
  vi.mocked(api.digitalHumans).mockResolvedValue(digitalHumanPage)
  vi.mocked(api.assetLibrary).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: { items: [], pagination: { total: 0, page: 1, page_size: 24, pages: 0 } },
  })
  vi.mocked(api.imageGenerationModels).mockResolvedValue({ code: 0, message: 'ok', data: [] })
  vi.mocked(api.asset).mockResolvedValue({ code: 0, message: 'ok', data: assetWithImage })
  vi.mocked(api.referencePromptPreview).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: { prompt: editedAsset.base_traits || '', prompt_language: 'zh' },
  })

  const wrapper = mount(AssetCreateDialog, {
    props: { open: true, kind: 'character', novelId: 9, asset: assetWithImage },
    global: { components: { AppButton }, stubs: { Teleport: true } },
  })
  await flushPromises()

  const image = wrapper.get<HTMLImageElement>('.asset-generated-preview img')
  expect(image.attributes('src')).toBe('/media/generated-character.png')
  expect(image.attributes('alt')).toBe('李火旺的生成图片')

  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  expect(wrapper.emitted('close')).toHaveLength(1)
  wrapper.unmount()
})

it('switches the top preview with the selected variant and shows a blank state for variants without images', async () => {
  vi.clearAllMocks()
  const assetWithImage = { ...editedAsset, main_image: '/media/base.png' }
  const variants: AssetVariant[] = [
    { id: 31, asset_id: 7, name: '练气期', images: ['/media/variant.png'], created_at: editedAsset.created_at, updated_at: editedAsset.updated_at },
    { id: 32, asset_id: 7, name: '受伤状态', images: [], created_at: editedAsset.created_at, updated_at: editedAsset.updated_at },
  ]
  vi.mocked(api.digitalHumans).mockResolvedValue(digitalHumanPage)
  vi.mocked(api.assetLibrary).mockResolvedValue({ code: 0, message: 'ok', data: { items: [], pagination: { total: 0, page: 1, page_size: 24, pages: 0 } } })
  vi.mocked(api.imageGenerationModels).mockResolvedValue({ code: 0, message: 'ok', data: [] })
  vi.mocked(api.asset).mockResolvedValue({ code: 0, message: 'ok', data: assetWithImage })
  vi.mocked(api.assetVariants).mockResolvedValue({ code: 0, message: 'ok', data: variants })
  vi.mocked(api.referencePromptPreview).mockResolvedValue({ code: 0, message: 'ok', data: { prompt: editedAsset.base_traits || '', prompt_language: 'zh' } })

  const wrapper = mount(AssetCreateDialog, {
    props: { open: true, kind: 'character', novelId: 9, asset: assetWithImage },
    global: { components: { AppButton }, stubs: { Teleport: true } },
  })
  await flushPromises()

  expect(wrapper.get<HTMLImageElement>('.asset-generated-preview img').attributes('src')).toBe('/media/base.png')
  await wrapper.get('button[aria-label="切换到练气期"]').trigger('click')
  expect(wrapper.get<HTMLImageElement>('.asset-generated-preview img').attributes('src')).toBe('/media/variant.png')
  expect(wrapper.get('.asset-generated-preview > header strong').text()).toContain('练气期')

  await wrapper.get('button[aria-label="切换到受伤状态"]').trigger('click')
  expect(wrapper.find('.asset-generated-preview img').exists()).toBe(false)
  expect(wrapper.get('.asset-generated-preview__empty').text()).toContain('暂无图片')
  expect(wrapper.get('.asset-generated-preview > header span').text()).toBe('尚未生成')

  await wrapper.get('button[aria-label="切换到主形象"]').trigger('click')
  expect(wrapper.get<HTMLImageElement>('.asset-generated-preview img').attributes('src')).toBe('/media/base.png')
})

it('renders as a right drawer and lists previous generation images', async () => {
  vi.clearAllMocks()
  const assetWithImage = { ...editedAsset, main_image: '/media/current.png' }
  vi.mocked(api.digitalHumans).mockResolvedValue(digitalHumanPage)
  vi.mocked(api.assetLibrary).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: { items: [], pagination: { total: 0, page: 1, page_size: 24, pages: 0 } },
  })
  vi.mocked(api.imageGenerationModels).mockResolvedValue({ code: 0, message: 'ok', data: [] })
  vi.mocked(api.asset).mockResolvedValue({ code: 0, message: 'ok', data: assetWithImage })
  vi.mocked(api.referencePromptPreview).mockResolvedValue({ code: 0, message: 'ok', data: { prompt: editedAsset.base_traits || '', prompt_language: 'zh' } })
  const fullFailureReason = '生图供应商返回错误（ROUTER_VALIDATION_ERROR，上游 HTTP 请求参数不符合模型协议，请检查图片尺寸和输出格式）'
  vi.mocked(api.assetGenerationHistory).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: [
      {
        id: 'run-1',
        status: 3,
        images: ['/media/history.png'],
        model: 'gpt-image-2',
        clarity: 'high',
        aspect_ratio: '3:2',
        output_format: 'png',
        created_at: '2026-08-13T09:00:00.000Z',
      },
      {
        id: 'run-failed',
        status: 4,
        images: [],
        error_message: fullFailureReason,
        model: 'gpt-image-2',
        created_at: '2026-08-13T08:58:00.000Z',
      },
      {
        id: 'run-failed-short',
        status: 4,
        images: [],
        error_message: '服务暂时不可用',
        model: 'gpt-image-2',
        created_at: '2026-08-13T08:57:00.000Z',
      },
    ],
  })
  vi.mocked(api.restoreAssetGeneration).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: { ...assetWithImage, main_image: '/media/history.png' },
  })

  const wrapper = mount(AssetCreateDialog, {
    props: { open: true, kind: 'character', novelId: 9, asset: assetWithImage },
    global: { components: { AppButton }, stubs: { Teleport: true } },
  })
  await flushPromises()

  expect(assetDialogSource).toContain('right: 0')
  expect(assetDialogSource).toContain('translateX(100%)')
  const currentImage = wrapper.get<HTMLImageElement>('.asset-generated-preview img')
  Object.defineProperty(currentImage.element, 'naturalWidth', { configurable: true, value: 1920 })
  Object.defineProperty(currentImage.element, 'naturalHeight', { configurable: true, value: 1080 })
  await currentImage.trigger('load')
  expect(wrapper.get('.asset-generated-preview > header span').text()).toBe('1920 × 1080 / PNG')
  expect(wrapper.get<HTMLImageElement>('.asset-generation-history__list img').attributes('src')).toBe('/media/history.png')
  expect(wrapper.get('.asset-generation-history__list').text()).toContain('gpt-image-2 / 3:2 / high / PNG')
  const historyList = wrapper.get('.asset-generation-history__list')
  expect(historyList.text()).toContain('服务暂时不可用')
  expect(wrapper.findAll('button[aria-label*="失败详情"]')).toHaveLength(1)
  const failureButton = wrapper.get('button[aria-label*="失败详情"]')
  expect(failureButton.text()).toContain('查看详情')
  expect(historyList.text()).not.toContain(fullFailureReason)
  expect(historyList.text()).toContain(`${fullFailureReason.slice(0, 20)}...`)
  expect(assetDialogSource).toContain('color: #c92f43')
  expect(assetDialogSource).toContain('font-size: 8px')
  await failureButton.trigger('click')
  expect(wrapper.get('.asset-generation-error-detail pre').text()).toContain(fullFailureReason)
  expect(assetDialogSource).toContain('overflow-wrap: anywhere')
  expect(assetDialogSource).toContain('overflow-x: hidden')
  await wrapper.get('button[aria-label="关闭失败详情"]').trigger('click')
  expect(wrapper.find('.asset-generation-error-detail').exists()).toBe(false)

  const restoreButton = wrapper.findAll('button').find(button => button.text().includes('设为当前'))
  expect(restoreButton).toBeDefined()
  await restoreButton!.trigger('click')
  await flushPromises()
  expect(api.restoreAssetGeneration).toHaveBeenCalledWith(editedAsset.id, 'run-1')
  expect(wrapper.emitted('saved')?.[0]?.[0]).toMatchObject({ main_image: '/media/history.png' })
  expect(wrapper.get<HTMLImageElement>('.asset-generated-preview img').attributes('src')).toBe('/media/history.png')

  await wrapper.get('.asset-generated-preview__viewer').trigger('click')
  await wrapper.vm.$nextTick()
  expect(wrapper.get('.image-lightbox').attributes('aria-label')).toBe('图片放大查看')
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  await wrapper.vm.$nextTick()
  expect(wrapper.find('.image-lightbox').exists()).toBe(false)
  expect(wrapper.emitted('close')).toBeUndefined()
  wrapper.unmount()
})
