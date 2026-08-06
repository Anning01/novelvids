import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import type { DigitalHuman } from '@/types'
import { AssetTypeEnum } from '@/types'
import { useWorkbenchStore } from '../store/workbenchStore'
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

const frameStub = { template: '<article><slot /></article>' }
const pickerStub = {
  emits: ['choose', 'close'],
  template: '<button data-choose-human type="button" @click="$emit(\'choose\', item)">选择测试数字人</button>',
  setup: () => ({ item: selectedHuman }),
}

it('replaces the placeholder icon with the selected digital-human preview', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useWorkbenchStore()
  const saveAsset = vi.spyOn(store, 'saveAsset').mockResolvedValue(undefined)
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
      stubs: {
        WorkbenchNodeFrame: frameStub,
        MediaLibraryPicker: pickerStub,
        WorkbenchPromptEditorPanel: true,
        WorkbenchSelect: true,
        WorkbenchSuggestedInput: true,
      },
    },
  })

  expect(wrapper.find('.workbench-library-reference__preview').exists()).toBe(false)
  await wrapper.get('[data-choose-human]').trigger('click')
  await flushPromises()

  expect(wrapper.get('.workbench-library-reference__preview').attributes()).toMatchObject({
    src: '/media/human-one.png',
    alt: 'human-one 数字人预览',
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
  await wrapper.get('[aria-label="展开三图角色的 3 张图片"]').trigger('click')
  expect(wrapper.find('[aria-label="三图角色图片列表"]').exists()).toBe(true)

  await wrapper.get('[aria-label="设三图角色参考图 1为主图"]').trigger('click')
  expect(setMainImage).toHaveBeenCalledWith(2, '/media/side.png')
  expect(wrapper.find('[aria-label="三图角色图片列表"]').exists()).toBe(false)
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
  expect(wrapper.text()).toContain('场景资产 · 等待生成图片')
})
