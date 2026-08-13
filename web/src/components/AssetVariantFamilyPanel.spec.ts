import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AssetVariantFamilyPanel from './AssetVariantFamilyPanel.vue'
import { api } from '@/api'
import { AssetTypeEnum, type Asset } from '@/types'

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

vi.mock('@/shared/notice', () => ({
  notice: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

const asset: Asset = {
  id: 7,
  novel_id: 9,
  asset_type: AssetTypeEnum.PERSON,
  canonical_name: '岳闻',
  main_image: '/media/yuewen.png',
  created_at: '2026-08-13T00:00:00Z',
  updated_at: '2026-08-13T00:00:00Z',
}

const variants = [
  {
    id: 31,
    asset_id: 7,
    name: '日常便装',
    description: '日常生活中的常见穿着',
    chapter_numbers: [1],
    images: ['/media/casual.png'],
    created_at: '2026-08-13T00:00:00Z',
    updated_at: '2026-08-13T00:00:00Z',
  },
]

describe('AssetVariantFamilyPanel', () => {
  beforeEach(() => {
    vi.mocked(api.assetVariants).mockResolvedValue({ code: 0, message: 'ok', data: variants })
  })

  it('shows the base asset separately from its derived states', async () => {
    const wrapper = mount(AssetVariantFamilyPanel, { props: { asset, chapterNumber: 1 } })
    await flushPromises()

    expect(wrapper.text()).toContain('默认形态')
    expect(wrapper.text()).toContain('日常便装')
    expect(wrapper.text()).toContain('本章使用')
    expect(wrapper.text()).toContain('新建衍生')
  })

  it('creates a derived state with episode assignments', async () => {
    vi.mocked(api.createAssetVariant).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { ...variants[0], id: 32, name: '受伤状态', chapter_numbers: [2, 5], images: [] },
    })
    const wrapper = mount(AssetVariantFamilyPanel, { props: { asset, chapterNumber: 1 } })
    await flushPromises()

    await wrapper.get('.variant-tile--new').trigger('click')
    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('受伤状态')
    await inputs[1].setValue('2，5')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(api.createAssetVariant).toHaveBeenCalledWith(7, expect.objectContaining({
      name: '受伤状态',
      chapter_numbers: [2, 5],
    }))
    expect(wrapper.text()).toContain('受伤状态')
  })

  it('makes one derived state the only state used by the current episode', async () => {
    const secondVariant = { ...variants[0], id: 32, name: '负伤后', chapter_numbers: [] }
    vi.mocked(api.assetVariants).mockResolvedValue({ code: 0, message: 'ok', data: [...variants, secondVariant] })
    vi.mocked(api.assignAssetVariantToChapter).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: [{ ...variants[0], chapter_numbers: [] }, { ...secondVariant, chapter_numbers: [1] }],
    })
    const wrapper = mount(AssetVariantFamilyPanel, { props: { asset, chapterNumber: 1 } })
    await flushPromises()

    await wrapper.get('[aria-label="将负伤后设为本章使用"]').trigger('click')
    await flushPromises()

    expect(api.assignAssetVariantToChapter).toHaveBeenCalledWith(7, 32, 1)
  })
})
