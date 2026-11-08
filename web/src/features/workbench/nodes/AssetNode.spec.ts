import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import { unref } from 'vue'
import type { Asset, AssetVariant, DigitalHuman } from '@/types'
import { AssetTypeEnum } from '@/types'
import { useWorkbenchStore } from '../store/workbenchStore'
import { createWorkbenchPromptActionRegistry, workbenchPromptActionRegistryKey } from '../prompt/promptActionRegistry'
import AssetNode from './AssetNode.vue'

const selectedHuman: DigitalHuman = {
  id: 1,
  country: '中国',
  age: 24,
  gender: '女',
  occupation: '模特',
  asset_id: 'human-one',
  image_url: '/media/human-one.png',
  is_active: true,
  created_at: '2026-07-25T00:00:00.000Z',
  updated_at: '2026-07-25T00:00:00.000Z',
}

const frameStub = {
  props: ['data'],
  template: '<article :data-body-draggable="data.body_draggable === true ? \'true\' : \'false\'"><slot name="icon" /><slot name="title" /><slot name="meta" /><slot name="toolbar-actions" /><slot /></article>',
}
const pickerStub = {
  props: ['open'],
  emits: ['choose', 'close'],
  template: '<button v-if="open" data-choose-human type="button" @click="$emit(\'choose\', item)">选择测试数字人</button>',
  setup: () => ({ item: selectedHuman }),
}

const promptPanelStub = {
  props: ['modelValue'],
  emits: ['update:modelValue', 'focusout'],
  template: '<textarea data-asset-prompt :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" @focusout="$emit(\'focusout\', $event)" />',
}

it.each(['light', 'dark'])('loads originals on the canvas and repairs thumbnail dimensions (%s)', async theme => {
  document.documentElement.dataset.appTheme = theme
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useWorkbenchStore()
  const updateMetadata = vi.spyOn(store, 'updateAssetImageMetadata').mockResolvedValue(null)
  const asset = {
    id: 90, novel_id: 9, asset_type: AssetTypeEnum.PERSON, canonical_name: '原图角色',
    main_image: '/media/original.png', main_image_thumbnail: '/media/original-thumbnail.webp',
    main_image_preview: '/media/original-preview.webp',
    angle_image_1: '/media/side.png', angle_image_1_thumbnail: '/media/side-thumbnail.webp',
    metadata: { workbenchImage: { width: 320, height: 180 } }, created_at: '', updated_at: '',
  }
  const wrapper = mount(AssetNode, {
    props: { id: 'asset-90', type: 'asset', selected: false, connectable: true,
      data: { asset, generate_capability: false } } as never,
    global: { plugins: [pinia], stubs: {
      WorkbenchNodeFrame: frameStub, MediaLibraryPicker: true, WorkbenchPromptEditorPanel: true,
      WorkbenchSelect: true, WorkbenchSuggestedInput: true, ImageAnnotationDialog: true,
    } },
  })
  const image = wrapper.get<HTMLImageElement>('.workbench-uploaded-image-preview')
  expect(image.attributes('src')).toBe('/media/original.png')
  expect(image.attributes('loading')).toBe('lazy')
  expect(wrapper.get('.workbench-asset-image-stack-layer img').attributes('src')).toBe('/media/side-thumbnail.webp')
  Object.defineProperties(image.element, { naturalWidth: { value: 2048 }, naturalHeight: { value: 1152 } })
  await image.trigger('load')
  expect(updateMetadata).toHaveBeenCalledWith(90, { width: 2048, height: 1152 }, undefined)
  expect(wrapper.get('.workbench-node-frame__media-size').text()).toBe('2048 × 1152')
  await wrapper.get('[aria-label="展开原图角色的 2 张图片"]').trigger('click')
  expect(wrapper.findAll('.workbench-asset-gallery__item img').map(item => item.attributes('src')))
    .toEqual(['/media/side.png', '/media/original.png'])
  await wrapper.get('[aria-label="收起原图角色的 2 张图片"]').trigger('click')
  await wrapper.setProps({ data: { asset: { ...asset, main_image: '/media/replacement.png',
    metadata: { workbenchImage: {} } }, generate_capability: false } })
  expect(wrapper.get('.workbench-uploaded-image-preview').attributes('src')).toBe('/media/replacement.png')
  expect(wrapper.find('.workbench-node-frame__media-size').exists()).toBe(false)
  wrapper.unmount()
  delete document.documentElement.dataset.appTheme
})

it('shows the asset-type icon picker on a new empty asset', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useWorkbenchStore()
  const saveAsset = vi.spyOn(store, 'saveAsset').mockResolvedValue(undefined)
  const wrapper = mount(AssetNode, {
    props: {
      id: 'asset-placeholder',
      type: 'asset',
      selected: true,
      connectable: true,
      data: {
        asset: {
          id: 8,
          novel_id: 9,
          asset_type: AssetTypeEnum.PERSON,
          canonical_name: '资产 1',
          metadata: { workbench_reusable_placeholder: true },
          created_at: '',
          updated_at: '',
        },
        generate_capability: false,
      },
    } as never,
    global: {
      plugins: [pinia],
      stubs: {
        WorkbenchNodeFrame: frameStub,
        MediaLibraryPicker: true,
        WorkbenchPromptEditorPanel: true,
        ProjectAssetPicker: true,
        ImageAnnotationDialog: true,
      },
    },
  })

  const picker = wrapper.get('[aria-label="资产类型"]')
  expect(picker.find('svg.lucide-user-round').exists()).toBe(true)
  expect(picker.element.closest('.workbench-select')?.classList.contains('is-placeholder-asset-type')).toBe(true)

  await picker.trigger('click')
  const assetTypeMenu = wrapper.get('[role="listbox"][aria-label="资产类型选项"]')
  expect(assetTypeMenu.findAll('[role="option"]').map(option => option.text())).toEqual(['人物', '物品', '场景'])
  expect(assetTypeMenu.text()).not.toContain('图片')
  expect(assetTypeMenu.text()).not.toContain('商品')
  expect(assetTypeMenu.text()).not.toContain('风格')
  await wrapper.get('[role="option"]:has(.lucide-mountain)').trigger('click')
  await flushPromises()

  expect(saveAsset).toHaveBeenCalledWith(8, expect.objectContaining({ asset_type: AssetTypeEnum.SCENE }))
  expect(wrapper.get('[aria-label="资产类型"]').find('svg.lucide-mountain').exists()).toBe(true)
})

it('binds the expanded asset editor to base_traits instead of description', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useWorkbenchStore()
  const saveAsset = vi.spyOn(store, 'saveAsset').mockResolvedValue(undefined)
  const actionRegistry = createWorkbenchPromptActionRegistry()
  const wrapper = mount(AssetNode, {
    props: {
      id: 'asset-prompt',
      type: 'asset',
      selected: true,
      connectable: true,
      data: {
        asset: {
          id: 9,
          novel_id: 9,
          asset_type: AssetTypeEnum.PERSON,
          canonical_name: '陈经理',
          description: '六九同城房产经理，是本章雇主。',
          base_traits: 'cinematic character reference, black suit, neutral studio light',
          metadata: {},
          created_at: '',
          updated_at: '',
        },
        generate_capability: false,
        prompt_editor_open: true,
        prompt_editor: {
          editorKey: 'asset_prompt',
          nodeKind: 'asset',
          fieldKey: 'prompt',
          label: '图片 Prompt',
          placeholder: '输入图片提示词',
          hint: '',
          allowedAssetTypes: null,
          excludedAssetTypes: null,
          referenceLimits: { image: 10, video: 0, audio: 0 },
          allowPromptInjection: false,
        },
      },
    } as never,
    global: {
      plugins: [pinia],
      provide: {
        [workbenchPromptActionRegistryKey as symbol]: actionRegistry,
      },
      stubs: {
        WorkbenchNodeFrame: frameStub,
        WorkbenchPromptEditorPanel: promptPanelStub,
        WorkbenchSelect: true,
        MediaLibraryPicker: true,
        ProjectAssetPicker: true,
        ImageAnnotationDialog: true,
      },
    },
  })

  const editor = wrapper.get<HTMLTextAreaElement>('[data-asset-prompt]')
  expect(editor.element.value).toBe('cinematic character reference, black suit, neutral studio light')
  expect(editor.element.value).not.toContain('六九同城房产经理')

  await editor.setValue('updated image generation prompt')
  await editor.trigger('focusout')
  await flushPromises()

  expect(saveAsset).toHaveBeenCalledWith(9, expect.objectContaining({
    description: '六九同城房产经理，是本章雇主。',
    base_traits: 'updated image generation prompt',
  }))
})

it('moves digital-human selection into the prompt footer control', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useWorkbenchStore()
  const saveAsset = vi.spyOn(store, 'saveAsset').mockResolvedValue(undefined)
  const actionRegistry = createWorkbenchPromptActionRegistry()
  const wrapper = mount(AssetNode, {
    props: {
      id: 'asset-1',
      type: 'asset',
      selected: false,
      dragging: false,
      connectable: true,
      position: { x: 0, y: 0 },
      dimensions: { width: 360, height: 640 },
      positionAbsoluteX: 0,
      positionAbsoluteY: 0,
      zIndex: 1,
      isValidTargetPos: () => true,
      isValidSourcePos: () => true,
      resizing: false,
      events: {},
      data: {
        asset: {
          id: 1,
          novel_id: 9,
          asset_type: AssetTypeEnum.PERSON,
          canonical_name: '李火旺',
          metadata: {},
          created_at: '2026-07-25T00:00:00.000Z',
          updated_at: '2026-07-25T00:00:00.000Z',
        },
        generate_capability: false,
      },
    } as never,
    global: {
      plugins: [pinia],
      provide: {
        [workbenchPromptActionRegistryKey as symbol]: actionRegistry,
      },
      stubs: {
        WorkbenchNodeFrame: frameStub,
        MediaLibraryPicker: pickerStub,
        WorkbenchPromptEditorPanel: true,
        WorkbenchSelect: true,
        WorkbenchSuggestedInput: true,
      },
    },
  })

  expect(wrapper.find('.workbench-library-reference').exists()).toBe(false)
  expect(wrapper.find('.workbench-asset-generation').exists()).toBe(false)
  expect(wrapper.find('fieldset').exists()).toBe(false)
  const controls = actionRegistry.actions.get('asset-1')?.[0]?.controls || []
  expect(controls.map(control => control.id)).toEqual([
    'asset-image-generation-model',
    'asset-image-generation-parameters',
    'asset-image-generation-digital-human',
  ])
  const digitalHumanControl = controls.find(control => control.id === 'asset-image-generation-digital-human')
  expect(digitalHumanControl).toBeTruthy()
  expect(wrapper.find('[data-choose-human]').exists()).toBe(false)
  digitalHumanControl?.events?.open?.()
  await flushPromises()
  await wrapper.get('[data-choose-human]').trigger('click')
  await flushPromises()

  expect(unref(digitalHumanControl?.props)).toMatchObject({
    title: 'human-one',
    previewUrl: '/media/human-one.png',
    selected: true,
  })
  expect(saveAsset).toHaveBeenCalledWith(1, expect.objectContaining({
    metadata: expect.objectContaining({
      workbench: expect.objectContaining({
        digitalHumanAssetId: 'human-one',
        digitalHumanPreviewUrl: '/media/human-one.png',
      }),
    }),
  }))
})

it('renders a stacked multi-image card and promotes an expanded gallery image', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useWorkbenchStore()
  const setMainImage = vi.spyOn(store, 'setAssetMainImage').mockResolvedValue(undefined as never)
  const wrapper = mount(AssetNode, {
    props: {
      id: 'asset-2',
      type: 'asset',
      selected: false,
      connectable: true,
      data: {
        asset: {
          id: 2,
          novel_id: 9,
          asset_type: AssetTypeEnum.PERSON,
          canonical_name: '三图角色',
          main_image: '/media/front.png',
          angle_image_1: '/media/side.png',
          metadata: { image_gallery: ['/media/front.png', '/media/side.png', '/media/back.png'] },
          created_at: '2026-07-30T00:00:00.000Z',
          updated_at: '2026-07-30T00:00:00.000Z',
        },
        generate_capability: false,
      },
    } as never,
    global: {
      plugins: [pinia],
      stubs: {
        WorkbenchNodeFrame: frameStub,
        MediaLibraryPicker: true,
        WorkbenchPromptEditorPanel: true,
        WorkbenchSelect: true,
        WorkbenchSuggestedInput: true,
      },
    },
  })

  expect(wrapper.findAll('.workbench-asset-image-stack-layer')).toHaveLength(2)
  expect(wrapper.get('.workbench-asset-image-stage').attributes('style')).toContain('margin-right: 8px')
  expect(wrapper.get('.workbench-asset-image-stage').attributes('style')).not.toContain('margin-bottom')
  expect(wrapper.findAll('.workbench-asset-image-stack-layer')[1]?.attributes('style')).toContain('translateX(8px)')
  expect(wrapper.get('article').attributes('data-body-draggable')).toBe('true')
  expect(wrapper.find('.workbench-asset-image-upload').exists()).toBe(false)
  expect(wrapper.find('.workbench-asset-generation').exists()).toBe(false)
  expect(wrapper.find('[aria-label="替换资产图片"]').exists()).toBe(true)
  await wrapper.get('[aria-label="管理衍生形态"]').trigger('click')
  expect(wrapper.find('[role="dialog"][aria-label="衍生形态管理"]').exists()).toBe(true)
  await wrapper.get('[aria-label="展开三图角色的 3 张图片"]').trigger('click')
  expect(wrapper.find('[aria-label="三图角色图片列表"]').exists()).toBe(true)
  expect(wrapper.findAll('.workbench-media-gallery__row').length).toBeGreaterThan(0)

  await wrapper.get('[aria-label="收起三图角色的 3 张图片"]').trigger('pointerdown')
  await wrapper.get('[aria-label="收起三图角色的 3 张图片"]').trigger('click')
  expect(wrapper.find('[aria-label="三图角色图片列表"]').exists()).toBe(false)

  await wrapper.get('[aria-label="展开三图角色的 3 张图片"]').trigger('click')

  await wrapper.get('[aria-label="设三图角色参考图 1为主图"]').trigger('click')
  expect(setMainImage).toHaveBeenCalledWith(2, '/media/side.png')
  expect(wrapper.find('[aria-label="三图角色图片列表"]').exists()).toBe(false)
})

it.each(['light', 'dark'])('keeps base and independent variant cards visible without mixing their edits (%s)', async theme => {
  document.documentElement.dataset.appTheme = theme
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useWorkbenchStore()
  const saveBase = vi.spyOn(store, 'saveAsset').mockResolvedValue(undefined)
  const empty: AssetVariant = { id: 7, asset_id: 1, name: '测试', description: '衍生说明',
    base_traits: '衍生设定', images: [], created_at: '', updated_at: '' }
  const generated: AssetVariant = { ...empty, id: 8, name: '换装', images: ['/variant.png'], base_traits: '换装设定' }
  const asset: Asset = { id: 1, novel_id: 9, canonical_name: '杜仲元', asset_type: AssetTypeEnum.PERSON,
    main_image: '/base.png', base_traits: '基础设定', metadata: { workbenchImage: { width: 320, height: 180 },
      workbench: { digitalHumanPreviewUrl: '/base-face.png' } }, variants: [generated], created_at: '', updated_at: '' }
  const data = { asset, generate_capability: false, prompt_editor_open: true, prompt_editor: {
    editorKey: 'asset_prompt', nodeKind: 'asset', fieldKey: 'prompt', label: '图片 Prompt', placeholder: '', hint: '',
    allowedAssetTypes: null, excludedAssetTypes: null, referenceLimits: { image: 10, video: 0, audio: 0 }, allowPromptInjection: false,
  } }
  const wrapper = mount(AssetNode, { props: { id: 'variant-asset', type: 'asset', selected: true,
    connectable: true, data } as never,
    global: { plugins: [pinia], stubs: { WorkbenchNodeFrame: frameStub, WorkbenchPromptEditorPanel: promptPanelStub,
      MediaLibraryPicker: true, WorkbenchSuggestedInput: true, ProjectAssetPicker: true, ImageAnnotationDialog: true } } })
  const create = vi.spyOn(store, 'createAssetVariant').mockImplementation(async () => {
    await wrapper.setProps({ data: { ...data, asset: { ...asset, variants: [generated, empty] } } })
    return empty
  })
  const saveVariant = vi.spyOn(store, 'saveAssetVariant').mockResolvedValue(generated)
  await wrapper.get('[aria-label="管理衍生形态"]').trigger('click')
  await wrapper.get('[aria-label="新增视觉形态"]').trigger('click')
  await wrapper.get('[aria-label="新形态名称"]').setValue('测试')
  await wrapper.get('.workbench-asset-variant-popover__create').trigger('submit')
  await flushPromises()
  expect(create).toHaveBeenCalledTimes(1)
  expect(wrapper.get('.workbench-uploaded-image-preview').attributes('src')).toBe('/base.png')
  expect(store.selectedNodeKeys).toEqual(['asset-1-variant-7'])
  const variantData = { ...data, asset: { ...asset, variants: [generated, empty] }, variant_id: 7 }
  const emptyCard = mount(AssetNode, { props: { id: 'asset-1-variant-7', type: 'asset', selected: true,
    connectable: true, data: variantData } as never,
    global: { plugins: [pinia], stubs: { WorkbenchNodeFrame: frameStub, WorkbenchPromptEditorPanel: promptPanelStub,
      MediaLibraryPicker: true, WorkbenchSuggestedInput: true, ProjectAssetPicker: true, ImageAnnotationDialog: true } } })
  expect(emptyCard.find('.workbench-uploaded-image-preview').exists()).toBe(false)
  expect(emptyCard.find('.workbench-asset-default-image img').exists()).toBe(false)
  expect(emptyCard.find('.workbench-node-frame__media-size').exists()).toBe(false)
  expect(emptyCard.get('[role="img"]').attributes('aria-label')).toBe('杜仲元 · 测试默认图片')
  const editor = emptyCard.get<HTMLTextAreaElement>('[data-asset-prompt]')
  expect(editor.element.value).toBe('衍生设定')
  await editor.setValue('调整后的衍生设定')
  await editor.trigger('focusout')
  await flushPromises()
  expect(saveVariant).toHaveBeenCalledWith(1, 7, expect.objectContaining({ base_traits: '调整后的衍生设定' }))
  expect(saveBase).not.toHaveBeenCalled()
  await emptyCard.setProps({ data: { ...variantData, asset: { ...asset, variants: [generated, { ...empty, images: ['/new-variant.png'] }] } } })
  expect(emptyCard.get('.workbench-uploaded-image-preview').attributes('src')).toBe('/new-variant.png')
  expect(wrapper.get('.workbench-uploaded-image-preview').attributes('src')).toBe('/base.png')
  expect(wrapper.get<HTMLTextAreaElement>('[data-asset-prompt]').element.value).toBe('基础设定')
  emptyCard.unmount()
  wrapper.unmount()
  delete document.documentElement.dataset.appTheme
})

it('uses the latest full default visual for an asset without an image', () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(AssetNode, {
    props: {
      id: 'asset-3',
      type: 'asset',
      selected: false,
      connectable: true,
      data: {
        asset: {
          id: 3,
          novel_id: 9,
          asset_type: AssetTypeEnum.SCENE,
          canonical_name: '中式室内',
          created_at: '2026-07-30T00:00:00.000Z',
          updated_at: '2026-07-30T00:00:00.000Z',
        },
        generate_capability: false,
      },
    } as never,
    global: {
      plugins: [pinia],
      stubs: {
        WorkbenchNodeFrame: frameStub,
        MediaLibraryPicker: true,
        WorkbenchPromptEditorPanel: true,
        WorkbenchSelect: true,
        WorkbenchSuggestedInput: true,
      },
    },
  })

  expect(wrapper.get('[role="img"]').attributes('aria-label')).toBe('中式室内默认图片')
  expect(wrapper.get<HTMLElement>('.workbench-asset-default-image').element.style.aspectRatio).toBe('16 / 9')
  expect(wrapper.text()).toContain('场景资产 · 等待生成图片')
})
