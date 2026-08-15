import { flushPromises, mount } from '@vue/test-utils'
import { parse } from '@vue/compiler-sfc'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import { AssetTypeEnum, TaskStatusEnum, type Asset, type AssetVariant, type DigitalHuman, type ImageGenerationModel, type PaginationResponse } from '@/types'
import AppButton from './AppButton.vue'
import AssetCreateDialog from './AssetCreateDialog.vue'
import EpisodeSelectionPicker from './EpisodeSelectionPicker.vue'
import ImageAnnotationEditor from './ImageAnnotationEditor.vue'
import assetDialogSource from './AssetCreateDialog.vue?raw'
import annotationEditorSource from './ImageAnnotationEditor.vue?raw'

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
    updateAsset: vi.fn(),
    assignAssetVariantToChapter: vi.fn(),
    deleteAssetVariant: vi.fn(),
    generateAsset: vi.fn(),
    task: vi.fn(),
    upload: vi.fn(),
    recordAssetImageEdit: vi.fn(),
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

it('keeps the drawer header compact', () => {
  const styles = parse(assetDialogSource).descriptor.styles.map(block => block.content).join('\n')
  expect(styles).toContain('grid-template-columns: 36px 1fr 32px')
  expect(styles).toContain('padding: 11px 18px')
  expect(styles).toContain('width: 36px; height: 36px')
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

it('keeps image annotation available for a selected variant and stores the result on that variant', async () => {
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
  vi.mocked(api.upload).mockResolvedValue({
    filename: 'assets/variant-annotated.png',
    original_filename: 'variant-annotated.png',
    content_type: 'image/png',
    file_path: '/tmp/variant-annotated.png',
  })
  const annotatedVariant: AssetVariant = {
    ...variants[0]!,
    images: ['/media/assets/variant-annotated.png', '/media/variant.png'],
  }
  vi.mocked(api.updateAssetVariant).mockResolvedValue({ code: 0, message: 'ok', data: annotatedVariant })

  const wrapper = mount(AssetCreateDialog, {
    props: { open: true, kind: 'character', novelId: 9, asset: assetWithImage },
    global: { components: { AppButton }, stubs: { Teleport: true } },
  })
  await flushPromises()

  expect(wrapper.get<HTMLImageElement>('.asset-generated-preview img').attributes('src')).toBe('/media/base.png')
  await wrapper.get('button[aria-label="切换到练气期"]').trigger('click')
  expect(wrapper.get<HTMLImageElement>('.asset-generated-preview img').attributes('src')).toBe('/media/variant.png')
  expect(wrapper.get('.asset-generated-preview > header strong').text()).toContain('练气期')
  const editButton = wrapper.get('button[aria-label="编辑当前图片标注"]')
  await editButton.trigger('click')
  const editor = wrapper.getComponent(ImageAnnotationEditor)
  expect(editor.props('open')).toBe(true)
  expect(editor.props('imageUrl')).toBe('/media/variant.png')

  editor.vm.$emit('save', new Blob(['annotated variant'], { type: 'image/png' }))
  await flushPromises()

  expect(api.updateAssetVariant).toHaveBeenCalledWith(editedAsset.id, variants[0]!.id, {
    images: ['/media/assets/variant-annotated.png', '/media/variant.png'],
  })
  expect(api.recordAssetImageEdit).not.toHaveBeenCalled()
  expect(editor.props('open')).toBe(false)
  expect(wrapper.get<HTMLImageElement>('.asset-generated-preview img').attributes('src')).toBe('/media/assets/variant-annotated.png')

  await wrapper.get('button[aria-label="切换到受伤状态"]').trigger('click')
  expect(wrapper.find('.asset-generated-preview img').exists()).toBe(false)
  expect(wrapper.get('.asset-generated-preview__empty').text()).toContain('暂无图片')
  expect(wrapper.get('.asset-generated-preview > header span').text()).toBe('尚未生成')

  await wrapper.get('button[aria-label="切换到主形象"]').trigger('click')
  expect(wrapper.get<HTMLImageElement>('.asset-generated-preview img').attributes('src')).toBe('/media/base.png')
})

it('uses application theme tokens for the preview edit action and annotation editor', () => {
  expect(assetDialogSource).toContain('color: var(--app-text-secondary)')
  expect(assetDialogSource).toContain('background: var(--app-surface-raised)')
  expect(annotationEditorSource).toContain('color:var(--app-text)')
  expect(annotationEditorSource).toContain('background:var(--app-surface)')
  expect(annotationEditorSource).toContain('border:1px solid var(--app-border-strong)')
  expect(annotationEditorSource).toContain('background:var(--app-accent-soft)')
})

it('shows a live animated generation state immediately after regeneration starts', async () => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  const assetWithBaseImage = { ...editedAsset, main_image: '/media/base.png' }
  const pendingVariant: AssetVariant = {
    id: 31,
    asset_id: editedAsset.id,
    name: '测试形态',
    description: '尚未生成图片的衍生形态',
    images: [],
    created_at: editedAsset.created_at,
    updated_at: editedAsset.updated_at,
  }
  vi.mocked(api.digitalHumans).mockResolvedValue(digitalHumanPage)
  vi.mocked(api.assetLibrary).mockResolvedValue({ code: 0, message: 'ok', data: { items: [], pagination: { total: 0, page: 1, page_size: 24, pages: 0 } } })
  vi.mocked(api.imageGenerationModels).mockResolvedValue({ code: 0, message: 'ok', data: [imageModel(12, '生成模型')] })
  vi.mocked(api.asset).mockResolvedValue({ code: 0, message: 'ok', data: assetWithBaseImage })
  vi.mocked(api.assetVariants).mockResolvedValue({ code: 0, message: 'ok', data: [pendingVariant] })
  vi.mocked(api.referencePromptPreview).mockResolvedValue({ code: 0, message: 'ok', data: { prompt: editedAsset.base_traits || '', prompt_language: 'zh' } })
  vi.mocked(api.updateAssetVariant).mockResolvedValue({ code: 0, message: 'ok', data: pendingVariant })
  vi.mocked(api.generateAsset).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: {
      id: 'generation-pending',
      task_type: 4,
      status: TaskStatusEnum.PENDING,
      created_at: '2026-08-14T10:00:00.000Z',
    },
  })
  vi.mocked(api.task).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: {
      id: 'generation-pending',
      task_type: 4,
      status: TaskStatusEnum.PROCESSING,
      created_at: '2026-08-14T10:00:00.000Z',
    },
  })

  const wrapper = mount(AssetCreateDialog, {
    props: { open: true, kind: 'character', novelId: 9, asset: assetWithBaseImage },
    global: { components: { AppButton }, stubs: { Teleport: true } },
  })
  await flushPromises()

  await wrapper.get('button[aria-label="切换到测试形态"]').trigger('click')
  const regenerateButton = wrapper.findAll('button').find(button => button.text().includes('生成图片'))
  expect(regenerateButton).toBeDefined()
  await regenerateButton!.trigger('click')
  await flushPromises()

  expect(api.generateAsset).toHaveBeenCalledWith(assetWithBaseImage.id, pendingVariant.id)
  expect(wrapper.get('.asset-generated-preview > header strong').text()).toContain('测试形态')
  expect(wrapper.get('.asset-generated-preview__generating').text()).toContain('生成中')
  expect(wrapper.get('.asset-generated-preview__generating').text()).toContain('自动显示最新结果')
  expect(wrapper.find('.asset-generated-preview__loader').exists()).toBe(true)
  expect(wrapper.get('.asset-generated-preview__status').text()).toContain('生成中')
  expect(regenerateButton!.attributes('aria-busy')).toBe('true')
  expect(regenerateButton!.text()).toContain('生成中')

  wrapper.unmount()
  vi.useRealTimers()
})

it('creates a derived state only from the drawer footer and persists the AI-assisted episode range', async () => {
  vi.clearAllMocks()
  const assetWithImage = { ...editedAsset, main_image: '/media/base.png' }
  const createdVariant: AssetVariant = {
    id: 45,
    asset_id: 7,
    name: '战损状态',
    description: '左臂受伤，衣服沾血',
    chapter_numbers: [2, 3, 4, 8],
    images: [],
    created_at: editedAsset.created_at,
    updated_at: editedAsset.updated_at,
  }
  vi.mocked(api.digitalHumans).mockResolvedValue(digitalHumanPage)
  vi.mocked(api.assetLibrary).mockResolvedValue({ code: 0, message: 'ok', data: { items: [], pagination: { total: 0, page: 1, page_size: 24, pages: 0 } } })
  vi.mocked(api.imageGenerationModels).mockResolvedValue({ code: 0, message: 'ok', data: [] })
  vi.mocked(api.asset).mockResolvedValue({ code: 0, message: 'ok', data: assetWithImage })
  vi.mocked(api.assetVariants).mockResolvedValue({ code: 0, message: 'ok', data: [] })
  vi.mocked(api.referencePromptPreview).mockResolvedValue({ code: 0, message: 'ok', data: { prompt: editedAsset.base_traits || '', prompt_language: 'zh' } })
  vi.mocked(api.createAssetVariant).mockResolvedValue({ code: 0, message: 'ok', data: createdVariant })

  const wrapper = mount(AssetCreateDialog, {
    props: { open: true, kind: 'character', novelId: 9, asset: assetWithImage, chapterNumber: 2, episodeNumbers: Array.from({ length: 10 }, (_, index) => index + 1) },
    global: { components: { AppButton }, stubs: { Teleport: true } },
  })
  await flushPromises()

  await wrapper.get('.asset-variant-item.is-add').trigger('click')
  await wrapper.get('.asset-variant-editor label:first-of-type input').setValue('战损状态')
  wrapper.getComponent(EpisodeSelectionPicker).vm.$emit('update:modelValue', [2, 3, 4, 8])
  await wrapper.get('.asset-variant-editor .is-description input').setValue('左臂受伤，衣服沾血')
  expect(wrapper.find('.asset-generated-preview img').exists()).toBe(false)
  expect(api.createAssetVariant).not.toHaveBeenCalled()

  await wrapper.get('.asset-dialog').trigger('submit')
  await flushPromises()

  expect(api.createAssetVariant).toHaveBeenCalledWith(7, expect.objectContaining({
    name: '战损状态',
    description: '左臂受伤，衣服沾血',
    chapter_numbers: [2, 3, 4, 8],
    metadata: expect.objectContaining({ editor_form: expect.objectContaining({ version: 1 }) }),
  }))
  expect(api.updateAsset).not.toHaveBeenCalled()
})

it('switches and persists an independent JSON form version for each derived state', async () => {
  vi.clearAllMocks()
  const assetWithBaseVersion: Asset = {
    ...editedAsset,
    main_image: '/media/base.png',
    metadata: {
      gender: '男',
      age_group: '中年',
      model_config_id: 12,
      clarity: 'medium',
      aspect_ratio: '1:1',
      output_format: 'png',
    },
  }
  const editorForm = {
    version: 1 as const,
    canonical_name: '李火旺·练气期',
    description: '练气期的独立角色描述',
    base_traits: '练气期白衣形态提示词',
    prompt_touched: true,
    creation_mode: 'ai' as const,
    gender: '男',
    age_group: '青年',
    voice: '青年音色',
    reference_layout: 'character_turnaround',
    model_config_id: 12,
    image_parameters: {
      clarity: 'high',
      aspect_ratio: '3:2',
      output_format: 'webp',
      generation_count: 1,
    },
    library_selection: { key: '', scope: 'all' as const },
  }
  const variant: AssetVariant = {
    id: 31,
    asset_id: 7,
    name: '练气期',
    base_traits: editorForm.base_traits,
    images: [],
    metadata: { editor_form: editorForm },
    created_at: editedAsset.created_at,
    updated_at: editedAsset.updated_at,
  }
  vi.mocked(api.digitalHumans).mockResolvedValue(digitalHumanPage)
  vi.mocked(api.assetLibrary).mockResolvedValue({ code: 0, message: 'ok', data: { items: [], pagination: { total: 0, page: 1, page_size: 24, pages: 0 } } })
  vi.mocked(api.imageGenerationModels).mockResolvedValue({ code: 0, message: 'ok', data: [imageModel(12, '版本模型')] })
  vi.mocked(api.asset).mockResolvedValue({ code: 0, message: 'ok', data: assetWithBaseVersion })
  vi.mocked(api.assetVariants).mockResolvedValue({ code: 0, message: 'ok', data: [variant] })
  vi.mocked(api.referencePromptPreview).mockResolvedValue({ code: 0, message: 'ok', data: { prompt: editedAsset.base_traits || '', prompt_language: 'zh' } })
  vi.mocked(api.updateAssetVariant).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: variant,
  })

  const wrapper = mount(AssetCreateDialog, {
    props: { open: true, kind: 'character', novelId: 9, asset: assetWithBaseVersion },
    global: { components: { AppButton }, stubs: { Teleport: true } },
  })
  await flushPromises()

  await wrapper.get('button[aria-label="切换到练气期"]').trigger('click')
  expect(wrapper.get<HTMLInputElement>('.asset-form-grid input').element.value).toBe('李火旺·练气期')
  expect(wrapper.get<HTMLTextAreaElement>('textarea[rows="8"]').element.value).toBe('练气期白衣形态提示词')
  expect(wrapper.findAll<HTMLTextAreaElement>('.asset-field textarea').at(-1)!.element.value).toBe('练气期的独立角色描述')

  await wrapper.get('button[aria-label="切换到主形象"]').trigger('click')
  expect(wrapper.get<HTMLInputElement>('.asset-form-grid input').element.value).toBe('李火旺')
  await wrapper.get('button[aria-label="切换到练气期"]').trigger('click')
  await wrapper.get<HTMLInputElement>('.asset-form-grid input').setValue('李火旺·练气后期')
  await wrapper.get<HTMLTextAreaElement>('textarea[rows="8"]').setValue('练气后期的新提示词')
  await wrapper.get('.asset-dialog').trigger('submit')
  await flushPromises()

  expect(api.updateAssetVariant).toHaveBeenCalledWith(7, 31, expect.objectContaining({
    base_traits: '练气后期的新提示词',
    metadata: expect.objectContaining({
      model_config_id: 12,
      clarity: 'high',
      aspect_ratio: '3:2',
      output_format: 'webp',
      editor_form: expect.objectContaining({
        version: 1,
        canonical_name: '李火旺·练气后期',
        base_traits: '练气后期的新提示词',
      }),
    }),
  }))
  expect(api.updateAsset).not.toHaveBeenCalled()
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

it('opens the image annotation editor and stores its export as a new generation record', async () => {
  vi.clearAllMocks()
  const assetWithImage = { ...editedAsset, main_image: '/media/assets/current.png' }
  const annotatedAsset: Asset = {
    ...assetWithImage,
    main_image: '/media/assets/annotated.png',
    metadata: {
      image_gallery: ['/media/assets/annotated.png', '/media/assets/current.png'],
      edited_generation_task_id: 'annotation-run',
    },
  }
  vi.mocked(api.digitalHumans).mockResolvedValue(digitalHumanPage)
  vi.mocked(api.assetLibrary).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: { items: [], pagination: { total: 0, page: 1, page_size: 24, pages: 0 } },
  })
  vi.mocked(api.imageGenerationModels).mockResolvedValue({ code: 0, message: 'ok', data: [] })
  vi.mocked(api.asset).mockResolvedValue({ code: 0, message: 'ok', data: assetWithImage })
  vi.mocked(api.assetGenerationHistory).mockResolvedValue({ code: 0, message: 'ok', data: [] })
  vi.mocked(api.referencePromptPreview).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: { prompt: editedAsset.base_traits || '', prompt_language: 'zh' },
  })
  vi.mocked(api.upload).mockResolvedValue({
    filename: 'assets/annotated.png',
    original_filename: 'annotated.png',
    content_type: 'image/png',
    file_path: '/tmp/annotated.png',
  })
  vi.mocked(api.recordAssetImageEdit).mockResolvedValue({ code: 0, message: 'ok', data: annotatedAsset })

  const wrapper = mount(AssetCreateDialog, {
    props: { open: true, kind: 'character', novelId: 9, asset: assetWithImage },
    global: { components: { AppButton }, stubs: { Teleport: true } },
  })
  await flushPromises()

  await wrapper.get('button[aria-label="编辑当前图片标注"]').trigger('click')
  const editor = wrapper.getComponent(ImageAnnotationEditor)
  expect(editor.props('open')).toBe(true)
  expect(editor.props('imageUrl')).toBe('/media/assets/current.png')

  editor.vm.$emit('save', new Blob(['annotated image'], { type: 'image/png' }))
  await flushPromises()

  expect(api.upload).toHaveBeenCalledTimes(1)
  const uploadedFile = vi.mocked(api.upload).mock.calls[0]?.[0]
  expect(uploadedFile).toBeInstanceOf(File)
  expect(uploadedFile?.type).toBe('image/png')
  expect(api.recordAssetImageEdit).toHaveBeenCalledWith(editedAsset.id, {
    image_url: '/media/assets/annotated.png',
    source_image_url: '/media/assets/current.png',
    output_format: 'png',
  })
  expect(wrapper.emitted('saved')?.[0]?.[0]).toEqual(annotatedAsset)
  expect(editor.props('open')).toBe(false)
  expect(api.assetGenerationHistory).toHaveBeenCalledTimes(2)
})
