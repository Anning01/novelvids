import { flushPromises, mount } from '@vue/test-utils'
import { parse } from '@vue/compiler-sfc'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import MaterialMentionInput from '@/features/workbench/components/MaterialMentionInput.vue'
import CatalogResourcePicker from '@/features/resource-library/CatalogResourcePicker.vue'
import { catalogApi } from '@/features/resource-library/catalog'
import AppSelect from './AppSelect.vue'
import { AssetTypeEnum, TaskStatusEnum, type Asset, type AssetVariant, type AudioReference, type DigitalHuman, type ImageGenerationModel, type PaginationResponse } from '@/types'
import AppButton from './AppButton.vue'
import AssetCreateDialog from './AssetCreateDialog.vue'
import AudioReferencePicker from './AudioReferencePicker.vue'
import EpisodeSelectionPicker from './EpisodeSelectionPicker.vue'
import ImageAnnotationEditor from './ImageAnnotationEditor.vue'
import assetDialogSource from './AssetCreateDialog.vue?raw'
import annotationEditorSource from './ImageAnnotationEditor.vue?raw'

vi.mock('@/api', () => ({
  mediaUrl: (path?: string | null) => path ?? '',
  persistedMediaRef: (uploaded: { key?: string; url?: string; filename: string }) =>
    uploaded.key || uploaded.url || `/media/${uploaded.filename}`,
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
    createAsset: vi.fn(),
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

vi.mock('@/features/resource-library/catalog', async (load) => {
  const original = await load<typeof import('@/features/resource-library/catalog')>()
  return { ...original, catalogApi: { ...original.catalogApi, projects: vi.fn(), projectCharacters: vi.fn() } }
})

beforeEach(() => {
  vi.mocked(catalogApi.projects).mockResolvedValue({ data: { items: [] } } as never)
  vi.mocked(api.assetGenerationHistory).mockResolvedValue({ code: 0, message: 'ok', data: [] })
  vi.mocked(api.assetVariants).mockResolvedValue({ code: 0, message: 'ok', data: [] })
})

it.each(['light', 'dark'])('filters the character library by project and discards outdated responses (%s)', async theme => {
  document.documentElement.dataset.appTheme = theme
  vi.mocked(api.digitalHumans).mockResolvedValue(digitalHumanPage)
  const empty = { code: 0, message: '', data: { items: [], pagination: { page: 1, pages: 0, page_size: 24, total: 0 } } }
  vi.mocked(api.assetLibrary).mockResolvedValue(empty)
  vi.mocked(api.imageGenerationModels).mockResolvedValue({ code: 0, message: '', data: [] })
  vi.mocked(catalogApi.projects).mockResolvedValue({ ...empty, data: { ...empty.data,
    items: [{ id: 20, name: '第一部作品' }, { id: 21, name: '第二部作品' }] } } as never)
  let finishFirst!: (result: PaginationResponse<Asset>) => void
  const first = { ...editedAsset, id: 80, novel_id: 20, canonical_name: '第一部的人物', main_image: '/media/first.png' }
  const second = { ...editedAsset, id: 81, novel_id: 21, canonical_name: '第二部的人物', main_image: '/media/second.png' }
  vi.mocked(catalogApi.projectCharacters)
    .mockImplementationOnce(() => new Promise(resolve => { finishFirst = resolve }))
    .mockResolvedValueOnce({ ...empty, data: { ...empty.data, items: [second] } })
  const w = mount(AssetCreateDialog, { props: { open: true, kind: 'character', novelId: 9, initialMode: 'library' },
    global: { components: { AppButton }, stubs: { Teleport: true } } })
  await flushPromises()
  await w.findAll('.asset-library nav button').find(button => button.text() === '项目人物')!.trigger('click')
  await flushPromises()
  const picker = w.findAllComponents(AppSelect).find(component => component.props('ariaLabel') === '按项目筛选')!
  expect(picker.props('searchable')).toBe(true)
  expect(picker.props('options')).toContainEqual({ value: '21', label: '第二部作品' })
  picker.vm.$emit('update:modelValue', '20')
  await w.vm.$nextTick()
  expect(w.get('.asset-library [role="status"]').text()).toContain('正在加载')
  picker.vm.$emit('update:modelValue', '21')
  await flushPromises()
  finishFirst({ ...empty, data: { ...empty.data, items: [first] } })
  await flushPromises()
  expect(w.findAll('.asset-library__card').map(card => card.text())).toEqual([`${second.canonical_name}${second.description}`])
  expect(catalogApi.projectCharacters).toHaveBeenNthCalledWith(1, 20)
  expect(catalogApi.projectCharacters).toHaveBeenNthCalledWith(2, 21)
  w.unmount()
  vi.mocked(catalogApi.projectCharacters).mockClear()
  delete document.documentElement.dataset.appTheme
})

it.each(['light', 'dark'])('keeps library originals and falls back to them when editor derivatives are missing (%s)', async theme => {
  document.documentElement.dataset.appTheme = theme
  vi.mocked(api.digitalHumans).mockResolvedValue(digitalHumanPage)
  const source = { ...editedAsset, id: 81, novel_id: 80, canonical_name:'角色库人物',
    main_image:'/media/source.png', main_image_thumbnail:'/media/derivatives/source-thumbnail.webp' }
  const current = { ...editedAsset, main_image:'/media/current.png', main_image_preview:'/media/derivatives/current-preview.webp' }
  vi.mocked(api.assetLibrary).mockResolvedValue({code:0,message:'',data:{items:[source],pagination:{page:1,pages:1,page_size:24,total:1}}})
  vi.mocked(api.imageGenerationModels).mockResolvedValue({code:0,message:'',data:[]})
  vi.mocked(api.asset).mockResolvedValue({code:0,message:'',data:current})
  vi.mocked(api.referencePromptPreview).mockResolvedValue({code:0,message:'',data:{prompt:'用户设定',prompt_language:'zh'}})
  vi.mocked(api.updateAsset).mockResolvedValue({code:0,message:'',data:{...current, main_image:source.main_image}})
  const w = mount(AssetCreateDialog,{props:{open:true,kind:'character',novelId:9,asset:current},global:{components:{AppButton},stubs:{Teleport:true}}})
  await flushPromises()
  const preview = w.get('.asset-generated-preview__viewer img')
  await preview.trigger('error')
  expect(preview.attributes('src')).toBe(current.main_image)
  const baseThumbnail = w.get('.asset-variant-item.is-base img')
  await baseThumbnail.trigger('error')
  expect(baseThumbnail.attributes('src')).toBe(current.main_image)
  await w.findAll('.asset-mode button').find(button => button.text().includes('从角色库选择'))!.trigger('click')
  const libraryCard = w.findAll('.asset-library__card').find(card => card.text().includes(source.canonical_name))!
  expect(libraryCard.get('img').attributes('src')).toBe(source.main_image_thumbnail)
  await libraryCard.trigger('click')
  await w.get('form').trigger('submit')
  await flushPromises()
  expect(api.updateAsset).toHaveBeenCalledWith(current.id,expect.objectContaining({main_image:source.main_image}),expect.anything())
  w.unmount()
  delete document.documentElement.dataset.appTheme
})

it('adds references from the character library, own variants and resources and keeps @ bindings after removal', async () => {
  vi.mocked(api.digitalHumans).mockResolvedValue(digitalHumanPage)
  vi.mocked(api.assetLibrary).mockResolvedValue({code:0,message:'',data:{items:[],pagination:{page:1,pages:0,page_size:24,total:0}}})
  vi.mocked(api.imageGenerationModels).mockResolvedValue({code:0,message:'',data:[imageModel(12,'图生图模型')]})
  const variant: AssetVariant = {id:31,asset_id:7,name:'白衣形态',images:['/media/white.png'],created_at:'',updated_at:''}
  vi.mocked(api.assetVariants).mockResolvedValue({code:0,message:'',data:[variant]})
  vi.mocked(api.asset).mockResolvedValue({code:0,message:'',data:editedAsset})
  vi.mocked(api.referencePromptPreview).mockResolvedValue({code:0,message:'',data:{prompt:'外观设定',prompt_language:'zh'}})
  vi.mocked(api.updateAsset).mockImplementation(async (_id,payload) => ({code:0,message:'',data:{...editedAsset,...payload} as Asset}))
  vi.mocked(api.generateAsset).mockResolvedValue({code:0,message:'',data:{id:'refs',task_type:2,status:TaskStatusEnum.COMPLETED,created_at:''}})
  const w = mount(AssetCreateDialog,{props:{open:true,kind:'character',novelId:9,asset:editedAsset},global:{components:{AppButton},stubs:{Teleport:true,CatalogResourcePicker:true}}})
  await flushPromises()
  await w.findAll('.asset-reference-sources button').find(button => button.text()==='角色库')!.trigger('click')
  await w.get('[aria-label="添加参考：多肉/花卉种植员"]').trigger('click')
  await w.findAll('.asset-reference-sources button').find(button => button.text()==='自身形态')!.trigger('click')
  await w.get('[aria-label="添加参考：白衣形态"]').trigger('click')
  await w.findAll('.asset-reference-sources button').find(button => button.text()==='资源库')!.trigger('click')
  w.getComponent(CatalogResourcePicker).vm.$emit('choose',[{url:'/media/costume.png'}])
  await flushPromises()
  expect(w.findAll('.asset-reference-input__grid figure')).toHaveLength(3)
  await w.get('[aria-label="引用参考图 2"]').trigger('click')
  await flushPromises()
  const editor = w.getComponent(MaterialMentionInput)
  expect(editor.props('modelValue')).toContain('@{参考图2}')
  expect(w.findAll('.workbench-inline-mention')).toHaveLength(1)
  await w.get('[aria-label="移除图生图参考图片 1"]').trigger('click')
  await flushPromises()
  expect(w.getComponent(MaterialMentionInput).props('modelValue')).toContain('@{参考图1}')
  expect(w.getComponent(MaterialMentionInput).props('mentions')[0]!.previewUrl).toBe('/media/white.png')
  await w.findAll('.asset-dialog__footer button').find(button => button.text().includes('生成图片'))!.trigger('click')
  await flushPromises()
  expect(api.generateAsset).toHaveBeenCalledWith(7,undefined,['/media/white.png','/media/costume.png'])
  expect(api.updateAsset).toHaveBeenCalledWith(7,expect.objectContaining({base_traits:expect.stringContaining('@{参考图1}'),metadata:expect.objectContaining({generation_reference_images:['/media/white.png','/media/costume.png']})}),expect.anything())
  w.unmount()
})

it('recovers an older library import whose main image was saved as a thumbnail', async () => {
  const original = { ...editedAsset, id:81, main_image:'/media/old-source.png', main_image_thumbnail:'/media/derivatives/old-source-thumbnail.webp' }
  const current = { ...editedAsset, main_image:original.main_image_thumbnail, metadata:{library_source:'project',source_asset_id:original.id} }
  vi.mocked(api.digitalHumans).mockResolvedValue(digitalHumanPage)
  vi.mocked(api.assetLibrary).mockResolvedValue({code:0,message:'',data:{items:[],pagination:{page:1,pages:0,page_size:24,total:0}}})
  vi.mocked(api.imageGenerationModels).mockResolvedValue({code:0,message:'',data:[]})
  vi.mocked(api.asset).mockImplementation(async id => ({code:0,message:'',data:id === original.id ? original : current}))
  vi.mocked(api.referencePromptPreview).mockResolvedValue({code:0,message:'',data:{prompt:'用户设定',prompt_language:'zh'}})
  const w = mount(AssetCreateDialog,{props:{open:true,kind:'character',novelId:9,asset:current},global:{components:{AppButton},stubs:{Teleport:true}}})
  await flushPromises()
  const preview = w.get('.asset-generated-preview__viewer img')
  await preview.trigger('error')
  expect(preview.attributes('src')).toBe(original.main_image)
  w.unmount()
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
      clarities: ['1K', '2K', '4K'],
      aspect_ratios: ['1:1', '3:2', '2:3'],
      output_formats: ['png', 'jpeg', 'webp'],
      generation_counts: [1],
      default_clarity: '1K',
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

it('notifies the outer card of a new asset generation before closing the drawer', async () => {
  vi.clearAllMocks()
  const created = { ...editedAsset, id: 21, asset_type: AssetTypeEnum.SCENE, canonical_name: '办公室' }
  vi.mocked(api.assetLibrary).mockResolvedValue({ code: 0, message: '', data: { items: [], pagination: { total: 0, page: 1, page_size: 24, pages: 0 } } })
  vi.mocked(api.imageGenerationModels).mockResolvedValue({ code: 0, message: '', data: [imageModel(1, '运行模型')] })
  vi.mocked(api.createAsset).mockResolvedValue({ code: 0, message: '', data: created })
  vi.mocked(api.generateAsset).mockResolvedValue({ code: 0, message: '', data: {
    id: 'new-image', task_type: 2, status: TaskStatusEnum.PENDING, created_at: '',
  } })
  const wrapper = mount(AssetCreateDialog, { props: { open: true, kind: 'scene', novelId: 9 },
    global: { components: { AppButton }, stubs: { Teleport: true } } })
  await flushPromises()
  await wrapper.get('input[placeholder="请输入"]').setValue('办公室')
  wrapper.getComponent(MaterialMentionInput).vm.$emit('update:modelValue', '保存的完整场景提示词')
  await flushPromises()
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(api.generateAsset).toHaveBeenCalledOnce()
  expect(wrapper.emitted('created')).toEqual([[created]])
  expect(wrapper.emitted('generation-started')).toEqual([[{ asset_id: 21, task_id: 'new-image', status: TaskStatusEnum.PENDING }]])
  expect(wrapper.emitted('close')).toHaveLength(1)
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

  expect(wrapper.getComponent(MaterialMentionInput).props('modelValue')).toContain('上半身正面平视特写')
  expect(wrapper.getComponent(MaterialMentionInput).props('modelValue')).not.toContain(editedAsset.description)

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

it('选择角色音色后立即保存绑定并更新当前资产', async () => {
  vi.clearAllMocks()
  const selectedVoice: AudioReference = {
    id: 19,
    nickname: '沉稳男声',
    gender: '男',
    audio_url: '/media/audio-references/steady.mp3',
    avatar_url: '',
    asset_id: 'upload-steady',
    source: 'upload',
    duration: 4,
    is_active: true,
    created_at: '',
    updated_at: '',
  }
  const asset = { ...editedAsset, canonical_name: '总工程师', metadata: {} }
  const updated = {
    ...asset,
    metadata: { voice: selectedVoice.nickname, voice_reference_id: selectedVoice.id },
  }
  vi.mocked(api.digitalHumans).mockResolvedValue(digitalHumanPage)
  vi.mocked(api.assetLibrary).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: { items: [], pagination: { total: 0, page: 1, page_size: 24, pages: 0 } },
  })
  vi.mocked(api.imageGenerationModels).mockResolvedValue({ code: 0, message: 'ok', data: [] })
  vi.mocked(api.asset).mockResolvedValue({ code: 0, message: 'ok', data: asset })
  vi.mocked(api.referencePromptPreview).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: { prompt: asset.base_traits || '', prompt_language: 'zh' },
  })
  vi.mocked(api.updateAsset).mockResolvedValue({ code: 0, message: 'ok', data: updated })

  const wrapper = mount(AssetCreateDialog, {
    props: { open: true, kind: 'character', novelId: 9, asset },
    global: { components: { AppButton }, stubs: { Teleport: true } },
  })
  await flushPromises()

  wrapper.findComponent(AudioReferencePicker).vm.$emit('choose', selectedVoice)
  await flushPromises()

  expect(api.updateAsset).toHaveBeenCalledWith(asset.id, {
    metadata: { voice: '沉稳男声', voice_reference_id: 19 },
  })
  expect(wrapper.emitted('saved')?.[0]).toEqual([updated])
  expect(wrapper.text()).toContain('沉稳男声')
})

async function mountVoiceEditor(asset: Asset, variant?: AssetVariant) {
  vi.mocked(api.digitalHumans).mockResolvedValue(digitalHumanPage)
  vi.mocked(api.assetLibrary).mockResolvedValue({ code: 0, message: 'ok', data: { items: [], pagination: { total: 0, page: 1, page_size: 24, pages: 0 } } })
  vi.mocked(api.imageGenerationModels).mockResolvedValue({ code: 0, message: 'ok', data: [] })
  vi.mocked(api.asset).mockResolvedValue({ code: 0, message: 'ok', data: asset })
  vi.mocked(api.assetVariants).mockResolvedValue({ code: 0, message: 'ok', data: variant ? [variant] : [] })
  vi.mocked(api.referencePromptPreview).mockResolvedValue({ code: 0, message: 'ok', data: { prompt: asset.base_traits || '', prompt_language: 'zh' } })
  const wrapper = mount(AssetCreateDialog, {
    props: { open: true, kind: 'character', novelId: 9, asset },
    global: { components: { AppButton }, stubs: { Teleport: true } },
  })
  await flushPromises()
  if (variant) await wrapper.get(`button[aria-label="切换到${variant.name}"]`).trigger('click')
  return wrapper
}

it.each(['light', 'dark'])('clears and persists the voice in %s mode with saving feedback', async theme => {
  document.documentElement.dataset.appTheme = theme
  const asset = { ...editedAsset, metadata: { voice: '沉稳男声', voice_reference_id: 19, gender: '男' } }
  const cleared = { ...asset, metadata: { ...asset.metadata, voice: '', voice_reference_id: null } }
  let finishSave!: (value: Awaited<ReturnType<typeof api.updateAsset>>) => void
  vi.mocked(api.updateAsset).mockImplementationOnce(() => new Promise(resolve => { finishSave = resolve }))
  const wrapper = await mountVoiceEditor(asset)
  try {
    await wrapper.get('button[aria-label="清除音色"]').trigger('click')
    expect(wrapper.get('button[aria-label="清除音色"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.asset-voice-choice').attributes('aria-busy')).toBe('true')
    expect(api.updateAsset).toHaveBeenLastCalledWith(asset.id, { metadata: cleared.metadata })
    finishSave({ code: 0, message: 'ok', data: cleared })
    await flushPromises()
    expect(wrapper.find('button[aria-label="清除音色"]').exists()).toBe(false)
    expect(wrapper.get('.asset-voice-choice').text()).toBe('选择音色')
    expect(wrapper.findComponent(AudioReferencePicker).props('selectedId')).toBeNull()
    expect(wrapper.emitted('saved')?.at(-1)).toEqual([cleared])
    wrapper.unmount()
    const reopened = await mountVoiceEditor(cleared)
    expect(reopened.get('.asset-voice-choice').text()).toBe('选择音色')
    expect(reopened.findComponent(AudioReferencePicker).props('selectedId')).toBeNull()
  } finally {
    delete document.documentElement.dataset.appTheme
  }
})

it('restores the selected voice if clearing fails', async () => {
  const asset = { ...editedAsset, metadata: { voice: '沉稳男声', voice_reference_id: 19 } }
  vi.mocked(api.updateAsset).mockRejectedValueOnce(new Error('Save failed'))
  const wrapper = await mountVoiceEditor(asset)
  await wrapper.get('button[aria-label="清除音色"]').trigger('click')
  await flushPromises()
  expect(wrapper.get('.asset-voice-choice').text()).toBe('沉稳男声')
  expect(wrapper.get('button[aria-label="清除音色"]').attributes('disabled')).toBeUndefined()
  expect(wrapper.findComponent(AudioReferencePicker).props('selectedId')).toBe(19)
})

it('keeps a cleared variant voice empty after reopening without changing the base voice', async () => {
  const asset = { ...editedAsset, metadata: { voice: '沉稳男声', voice_reference_id: 19 } }
  const variant: AssetVariant = { id: 31, asset_id: asset.id, name: '青年', base_traits: '青年形象', images: [],
    metadata: { voice: '青年音色', voice_reference_id: 20 }, created_at: '', updated_at: '' }
  const cleared: AssetVariant = { ...variant, metadata: { voice: '', voice_reference_id: null,
    editor_form: { voice: '', voice_reference_id: null } } }
  vi.mocked(api.updateAssetVariant).mockResolvedValueOnce({ code: 0, message: 'ok', data: cleared })
  const wrapper = await mountVoiceEditor(asset, variant)
  await wrapper.get('button[aria-label="清除音色"]').trigger('click')
  await flushPromises()
  expect(api.updateAssetVariant).toHaveBeenLastCalledWith(asset.id, variant.id, { metadata: cleared.metadata })
  await wrapper.get('button[aria-label="切换到主形象"]').trigger('click')
  expect(wrapper.get('.asset-voice-choice').text()).toBe('沉稳男声')
  wrapper.unmount()
  const reopened = await mountVoiceEditor(asset, cleared)
  expect(reopened.get('.asset-voice-choice').text()).toBe('选择音色')
  expect(reopened.findComponent(AudioReferencePicker).props('selectedId')).toBeNull()
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
  expect(image.attributes('src')).toBe('/media/derivatives/generated-character-preview.webp')
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

  expect(wrapper.get<HTMLImageElement>('.asset-generated-preview img').attributes('src')).toBe('/media/derivatives/base-preview.webp')
  await wrapper.get('button[aria-label="切换到练气期"]').trigger('click')
  expect(wrapper.get<HTMLImageElement>('.asset-generated-preview img').attributes('src')).toBe('/media/derivatives/variant-preview.webp')
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
  expect(wrapper.get<HTMLImageElement>('.asset-generated-preview img').attributes('src')).toBe('/media/assets/derivatives/variant-annotated-preview.webp')

  await wrapper.get('button[aria-label="切换到受伤状态"]').trigger('click')
  expect(wrapper.find('.asset-generated-preview img').exists()).toBe(false)
  expect(wrapper.get('.asset-generated-preview__empty').text()).toContain('暂无图片')
  expect(wrapper.get('.asset-generated-preview > header span').text()).toBe('尚未生成')

  await wrapper.get('button[aria-label="切换到主形象"]').trigger('click')
  expect(wrapper.get<HTMLImageElement>('.asset-generated-preview img').attributes('src')).toBe('/media/derivatives/base-preview.webp')
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
  expect(wrapper.emitted('generation-started')).toEqual([[{ asset_id: editedAsset.id, variant_id: pendingVariant.id, task_id: 'generation-pending', status: TaskStatusEnum.PENDING }]])
  expect(wrapper.get('.asset-generated-preview > header strong').text()).toContain('测试形态')
  expect(wrapper.get('.asset-generated-preview__generating').text()).toContain('生成中')
  expect(wrapper.get('.asset-generated-preview__generating').text()).toContain('自动显示最新结果')
  expect(wrapper.find('.asset-generated-preview__loader').exists()).toBe(true)
  expect(wrapper.get('.asset-generated-preview__status').text()).toContain('生成中')
  expect(regenerateButton!.attributes('aria-busy')).toBe('true')
  expect(regenerateButton!.text()).toContain('生成中')

  vi.mocked(api.task).mockResolvedValue({ code: 0, message: '', data: {
    id: 'generation-pending', task_type: 2, status: TaskStatusEnum.PROCESSING,
    stage: 'waiting_dependencies', created_at: '',
  } })
  await vi.advanceTimersByTimeAsync(2000)
  await flushPromises()
  expect(wrapper.get('.asset-generated-preview__generating').text()).toContain('等待参考图')
  expect(wrapper.get('.asset-generated-preview__generating').text()).toContain('上游失败时会保持等待')
  expect(wrapper.get('.asset-generated-preview__generating').attributes('role')).toBe('status')
  wrapper.unmount()
  vi.useRealTimers()
})

it('uploads an image-to-image reference and sends it with storyboard asset generation', async () => {
  vi.clearAllMocks()
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:reference-preview') })
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
  const assetWithImage = { ...editedAsset, main_image: '/media/base.png' }
  vi.mocked(api.digitalHumans).mockResolvedValue(digitalHumanPage)
  vi.mocked(api.assetLibrary).mockResolvedValue({ code: 0, message: 'ok', data: { items: [], pagination: { total: 0, page: 1, page_size: 24, pages: 0 } } })
  vi.mocked(api.imageGenerationModels).mockResolvedValue({ code: 0, message: 'ok', data: [imageModel(12, '图生图模型')] })
  vi.mocked(api.asset).mockResolvedValue({ code: 0, message: 'ok', data: assetWithImage })
  vi.mocked(api.referencePromptPreview).mockResolvedValue({ code: 0, message: 'ok', data: { prompt: editedAsset.base_traits || '', prompt_language: 'zh' } })
  vi.mocked(api.upload).mockResolvedValue({
    filename: 'reference.png',
    original_filename: 'reference.png',
    content_type: 'image/png',
    file_path: '/tmp/reference.png',
    key: 'uploads/9/reference.png',
  })
  vi.mocked(api.updateAsset).mockImplementation(async (_id, payload) => ({
    code: 0,
    message: 'ok',
    data: { ...assetWithImage, ...payload } as Asset,
  }))
  vi.mocked(api.generateAsset).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: {
      id: 'generation-with-reference',
      task_type: 4,
      status: TaskStatusEnum.COMPLETED,
      created_at: '2026-08-22T10:00:00.000Z',
    },
  })

  const wrapper = mount(AssetCreateDialog, {
    props: { open: true, kind: 'character', novelId: 9, asset: assetWithImage },
    global: { components: { AppButton }, stubs: { Teleport: true } },
  })
  await flushPromises()

  const input = wrapper.get<HTMLInputElement>('.asset-reference-input input[type="file"]')
  const file = new File(['reference'], 'reference.png', { type: 'image/png' })
  Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })
  await input.trigger('change')
  expect(wrapper.get('.asset-reference-input').text()).toContain('1/10')

  const generateButton = wrapper.findAll('button').find(button => button.text().includes('生成图片'))
  expect(generateButton).toBeDefined()
  await generateButton!.trigger('click')
  await flushPromises()

  expect(api.upload).toHaveBeenCalledWith(file, 12)
  expect(api.updateAsset).toHaveBeenCalledWith(assetWithImage.id, expect.objectContaining({
    metadata: expect.objectContaining({
      generation_reference_images: ['uploads/9/reference.png'],
    }),
  }), assetWithImage.base_traits)
  expect(api.generateAsset).toHaveBeenCalledWith(
    assetWithImage.id,
    undefined,
    ['uploads/9/reference.png'],
  )
  wrapper.unmount()
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
      clarity: '1K',
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
      clarity: '4K',
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
  expect(wrapper.getComponent(MaterialMentionInput).props('modelValue')).toBe('练气期白衣形态提示词')
  expect(wrapper.findAll<HTMLTextAreaElement>('.asset-field textarea').at(-1)!.element.value).toBe('练气期的独立角色描述')

  await wrapper.get('button[aria-label="切换到主形象"]').trigger('click')
  expect(wrapper.get<HTMLInputElement>('.asset-form-grid input').element.value).toBe('李火旺')
  await wrapper.get('button[aria-label="切换到练气期"]').trigger('click')
  await wrapper.get<HTMLInputElement>('.asset-form-grid input').setValue('李火旺·练气后期')
  wrapper.getComponent(MaterialMentionInput).vm.$emit('update:modelValue', '练气后期的新提示词')
  await flushPromises()
  await wrapper.get('.asset-dialog').trigger('submit')
  await flushPromises()

  expect(api.updateAssetVariant).toHaveBeenCalledWith(7, 31, expect.objectContaining({
    base_traits: '练气后期的新提示词',
    metadata: expect.objectContaining({
      model_config_id: 12,
      clarity: '4K',
      aspect_ratio: '3:2',
      output_format: 'webp',
      editor_form: expect.objectContaining({
        version: 1,
        canonical_name: '李火旺·练气后期',
        base_traits: '练气后期的新提示词',
      }),
    }),
  }), '练气期白衣形态提示词')
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
        id: 'run-current',
        status: 3,
        is_current: true,
        images: ['/media/current.png'],
        model: 'gpt-image-2',
        created_at: '2026-08-13T09:01:00.000Z',
      },
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
  expect(wrapper.get('.asset-generated-preview > header span').text()).toBe('PNG')
  expect(wrapper.get<HTMLImageElement>('.asset-generation-history__list img').attributes('src')).toBe('/media/derivatives/history-thumbnail.webp')
  expect(wrapper.get('.asset-generation-history > header').text()).toContain('3 次')
  expect(wrapper.get('.asset-generation-history__list').text()).not.toContain('当前使用')
  expect(wrapper.get('.asset-generation-history__list').text()).toContain('gpt-image-2 / 3:2 / high / PNG')
  const historyList = wrapper.get('.asset-generation-history__list')
  expect(historyList.text()).toContain('服务暂时不可用')
  expect(wrapper.findAll('button[aria-label*="失败详情"]')).toHaveLength(1)
  const failureButton = wrapper.get('button[aria-label*="失败详情"]')
  expect(failureButton.text()).toContain('查看详情')
  expect(historyList.text()).not.toContain(fullFailureReason)
  expect(historyList.text()).toContain(`${fullFailureReason.slice(0, 20)}...`)
  expect(assetDialogSource).toContain('color: var(--creation-danger)')
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
  expect(wrapper.get<HTMLImageElement>('.asset-generated-preview img').attributes('src')).toBe('/media/derivatives/history-preview.webp')
  const visibleHistoryImages = wrapper.findAll<HTMLImageElement>('.asset-generation-history__list img').map(image => image.attributes('src'))
  expect(visibleHistoryImages).toContain('/media/derivatives/current-thumbnail.webp')
  expect(visibleHistoryImages).not.toContain('/media/derivatives/history-thumbnail.webp')

  await wrapper.get('.asset-generated-preview__viewer').trigger('click')
  await wrapper.vm.$nextTick()
  expect(wrapper.get('.image-lightbox').attributes('aria-label')).toBe('图片放大查看')
  expect(wrapper.get<HTMLImageElement>('.image-lightbox img').attributes('src')).toBe('/media/history.png')
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

it('保存标注图时只向服务端传 key（OSS 直传），避免签名 URL 过期', async () => {
  vi.clearAllMocks()
  const assetWithImage = { ...editedAsset, main_image: '/media/assets/current.png' }
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
    data: { prompt: '', prompt_language: 'zh' },
  })
  // 直传 OSS：返回带签名的 public_url 与裸 key；我们应当只把 key 传给后端。
  vi.mocked(api.upload).mockResolvedValue({
    filename: '李七夜-annotation-1787227618985.png',
    original_filename: '李七夜-annotation-1787227618985.png',
    content_type: 'image/png',
    file_path: 'https://dramas-x.oss-cn-guangzhou.aliyuncs.com/uploads/.../x.png?Expires=...&Signature=...',
    url: 'https://dramas-x.oss-cn-guangzhou.aliyuncs.com/uploads/.../x.png?Expires=...&Signature=...',
    key: 'uploads/0/20260820/abc-李七夜-annotation-1787227618985.png',
  })
  vi.mocked(api.recordAssetImageEdit).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: { ...assetWithImage, main_image: 'uploads/0/20260820/abc-李七夜-annotation-1787227618985.png' },
  })

  const wrapper = mount(AssetCreateDialog, {
    props: { open: true, kind: 'character', novelId: 9, asset: assetWithImage },
    global: { components: { AppButton }, stubs: { Teleport: true } },
  })
  await flushPromises()

  await wrapper.get('button[aria-label="编辑当前图片标注"]').trigger('click')
  const editor = wrapper.getComponent(ImageAnnotationEditor)
  editor.vm.$emit('save', new Blob(['annotated'], { type: 'image/png' }))
  await flushPromises()

  expect(api.recordAssetImageEdit).toHaveBeenCalledWith(editedAsset.id, {
    image_url: 'uploads/0/20260820/abc-李七夜-annotation-1787227618985.png',
    source_image_url: '/media/assets/current.png',
    output_format: 'png',
  })
})

it('opens the requested variant with its own prompt without requiring a manual selection', async () => {
  const variant: AssetVariant = { id: 31, asset_id: 7, name: '雨衣形态', base_traits: '独立的蓝色雨衣设定', images: [], created_at: '', updated_at: '' }
  vi.mocked(api.digitalHumans).mockResolvedValue(digitalHumanPage)
  vi.mocked(api.assetLibrary).mockResolvedValue({ code: 0, message: '', data: { items: [], pagination: { total: 0, page: 1, page_size: 24, pages: 0 } } })
  vi.mocked(api.imageGenerationModels).mockResolvedValue({ code: 0, message: '', data: [] })
  vi.mocked(api.asset).mockResolvedValue({ code: 0, message: '', data: editedAsset })
  vi.mocked(api.assetVariants).mockResolvedValue({ code: 0, message: '', data: [variant] })
  vi.mocked(api.referencePromptPreview).mockResolvedValue({ code: 0, message: '', data: { prompt: '', prompt_language: 'zh' } })
  const wrapper = mount(AssetCreateDialog, { props: { open: true, kind: 'character', novelId: 9, asset: editedAsset, initialVariantId: 31 }, global: { stubs: { Teleport: true } } })
  await flushPromises()
  expect(wrapper.getComponent(MaterialMentionInput).props('modelValue')).toBe(variant.base_traits)
  expect(wrapper.get('.asset-variant-item.is-selected').text()).toContain('雨衣形态')
  wrapper.unmount()
})
