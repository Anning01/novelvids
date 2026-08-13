import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import SceneAssetVariantPicker from './SceneAssetVariantPicker.vue'
import { AssetTypeEnum, type Asset } from '@/types'

const assets: Asset[] = [
  {
    id: 1,
    novel_id: 7,
    asset_type: AssetTypeEnum.PERSON,
    canonical_name: '艾伦',
    aliases: ['团长'],
    main_image: '/media/eren-base.png',
    variants: [
      {
        id: 11,
        asset_id: 1,
        name: '日常便装与义肢',
        description: '受伤后的便装形态',
        images: ['/media/eren-injured.png'],
        created_at: '',
        updated_at: '',
      },
    ],
    created_at: '',
    updated_at: '',
  },
  {
    id: 2,
    novel_id: 7,
    asset_type: AssetTypeEnum.PERSON,
    canonical_name: '雷恩',
    variants: [],
    created_at: '',
    updated_at: '',
  },
]

afterEach(() => {
  document.body.innerHTML = ''
})

describe('SceneAssetVariantPicker', () => {
  it('shows asset subjects and their variants in separate columns', () => {
    const wrapper = mount(SceneAssetVariantPicker, {
      props: {
        open: true,
        anchorId: 'missing-test-anchor',
        label: '出镜角色',
        assets,
        selectedAssetIds: [],
        selectedVariantIds: {},
      },
      global: { stubs: { Teleport: true } },
    })

    expect(wrapper.text()).toContain('艾伦')
    expect(wrapper.text()).toContain('1 个衍生状态')
    expect(wrapper.text()).toContain('基础形态')
    expect(wrapper.text()).toContain('艾伦 · 日常便装与义肢')
  })

  it('emits the concrete asset variant selection and can deselect it', async () => {
    const wrapper = mount(SceneAssetVariantPicker, {
      props: {
        open: true,
        anchorId: 'missing-test-anchor',
        label: '出镜角色',
        assets,
        selectedAssetIds: [],
        selectedVariantIds: {},
      },
      global: { stubs: { Teleport: true } },
    })

    const variantButton = wrapper.findAll('.scene-asset-variant-picker__variants button')[1]!
    await variantButton.trigger('click')
    expect(wrapper.emitted('select')).toEqual([[{ assetId: 1, variantId: 11, selected: true }]])

    await wrapper.setProps({ selectedAssetIds: [1], selectedVariantIds: { 1: 11 } })
    await variantButton.trigger('click')
    expect(wrapper.emitted('select')?.[1]).toEqual([{ assetId: 1, variantId: 11, selected: false }])
  })

  it('searches aliases and variant names and closes with Escape', async () => {
    const wrapper = mount(SceneAssetVariantPicker, {
      props: {
        open: true,
        anchorId: 'missing-test-anchor',
        label: '出镜角色',
        assets,
        selectedAssetIds: [],
        selectedVariantIds: {},
      },
      global: { stubs: { Teleport: true } },
    })

    await wrapper.get('input[type="search"]').setValue('义肢')
    expect(wrapper.text()).toContain('艾伦')
    expect(wrapper.text()).not.toContain('雷恩')

    await wrapper.get('input[type="search"]').trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('always selects one result in replacement mode instead of toggling it off', async () => {
    const wrapper = mount(SceneAssetVariantPicker, {
      props: {
        open: true,
        anchorId: 'missing-test-anchor',
        label: '出镜角色',
        assets,
        selectedAssetIds: [1],
        selectedVariantIds: { 1: null },
        initialAssetId: 1,
        selectionMode: 'replace',
        placement: 'below',
      },
      global: { stubs: { Teleport: true } },
    })

    expect(wrapper.get('[role="dialog"]').attributes('aria-label')).toBe('替换出镜角色及衍生状态')
    expect(wrapper.get('input[type="search"]').attributes('placeholder')).toBe('搜索替换出镜角色或衍生状态')
    await wrapper.findAll('.scene-asset-variant-picker__variants button')[0]!.trigger('click')
    expect(wrapper.emitted('select')).toEqual([[{ assetId: 1, variantId: null, selected: true }]])
  })
})
