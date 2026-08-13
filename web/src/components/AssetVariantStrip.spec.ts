import { flushPromises, mount } from '@vue/test-utils'
import { parse } from '@vue/compiler-sfc'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AssetVariantStrip from './AssetVariantStrip.vue'
import assetVariantStripSource from './AssetVariantStrip.vue?raw'
import { api } from '@/api'
import { AssetTypeEnum, type Asset, type AssetVariant } from '@/types'

vi.mock('@/api', async importOriginal => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      assetVariants: vi.fn(),
      createAssetVariant: vi.fn(),
      updateAssetVariant: vi.fn(),
      assignAssetVariantToChapter: vi.fn(),
      deleteAssetVariant: vi.fn(),
    },
  }
})

vi.mock('@/shared/notice', () => ({ notice: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }))
vi.mock('@/shared/confirmDialog', () => ({ appConfirm: vi.fn().mockResolvedValue(true) }))

const asset: Asset = {
  id: 7,
  novel_id: 9,
  asset_type: AssetTypeEnum.PERSON,
  canonical_name: '岳闻',
  main_image: '/media/base.png',
  created_at: '2026-08-13T00:00:00Z',
  updated_at: '2026-08-13T00:00:00Z',
}

const variant: AssetVariant = {
  id: 31,
  asset_id: 7,
  name: '日常便装',
  description: '白色上衣',
  chapter_numbers: [1],
  images: ['/media/casual.png'],
  created_at: '2026-08-13T00:00:00Z',
  updated_at: '2026-08-13T00:00:00Z',
}

describe('AssetVariantStrip', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.assetVariants).mockResolvedValue({ code: 0, message: 'ok', data: [variant] })
  })

  it('shows a compact base-to-derived strip and marks the episode state', async () => {
    const wrapper = mount(AssetVariantStrip, { props: { asset, chapterNumber: 1 } })
    await flushPromises()

    expect(wrapper.text()).toContain('主形象')
    expect(wrapper.text()).toContain('日常便装')
    expect(wrapper.text()).toContain('添加变装')
    expect(wrapper.get('.asset-variant-item.is-current').text()).toContain('本集')
  })

  it('reserves enough rail space for the floating delete icon', () => {
    const styles = parse(assetVariantStripSource).descriptor.styles.map(block => block.content).join('\n')
    expect(styles).toContain('padding: 10px 9px 8px')
    expect(styles).toContain('top: -7px')
  })

  it('creates a new derived state from the inline editor', async () => {
    vi.mocked(api.createAssetVariant).mockResolvedValue({ code: 0, message: 'ok', data: { ...variant, id: 32, name: '受伤状态', chapter_numbers: [2], images: [] } })
    const wrapper = mount(AssetVariantStrip, { props: { asset, chapterNumber: 2 } })
    await flushPromises()

    await wrapper.get('.asset-variant-item.is-add').trigger('click')
    const inputs = wrapper.findAll('.asset-variant-editor input')
    await inputs[0].setValue('受伤状态')
    await inputs[1].setValue('2')
    await wrapper.get('.asset-variant-editor').trigger('submit')
    await flushPromises()

    expect(api.createAssetVariant).toHaveBeenCalledWith(7, expect.objectContaining({ name: '受伤状态', chapter_numbers: [2] }))
    expect(wrapper.text()).toContain('受伤状态')
    expect(wrapper.emitted('select')?.at(-1)?.[0]).toMatchObject({ id: 32, images: [] })
    expect(wrapper.get('.asset-variant-item.is-selected').text()).toContain('受伤状态')
  })

  it('switches between the base image and a derived image without falling back for empty variants', async () => {
    const emptyVariant = { ...variant, id: 33, name: '练气期', images: [] }
    vi.mocked(api.assetVariants).mockResolvedValue({ code: 0, message: 'ok', data: [variant, emptyVariant] })
    const wrapper = mount(AssetVariantStrip, { props: { asset, chapterNumber: 1 } })
    await flushPromises()

    const variantButtons = wrapper.findAll('.asset-variant-item__open')
    await variantButtons[0].trigger('click')
    expect(wrapper.emitted('select')?.at(-1)?.[0]).toEqual(variant)

    await variantButtons[1].trigger('click')
    expect(wrapper.emitted('select')?.at(-1)?.[0]).toEqual(emptyVariant)
    expect(variantButtons[1].find('img').exists()).toBe(false)

    await wrapper.get('.asset-variant-item.is-base').trigger('click')
    expect(wrapper.emitted('select')?.at(-1)?.[0]).toBeNull()
  })
})
