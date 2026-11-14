import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/api'
import { AssetTypeEnum, type Asset, type ImageGenerationModel } from '@/types'
import AppButton from './AppButton.vue'
import AssetBatchGenerateDialog from './AssetBatchGenerateDialog.vue'

vi.mock('@/api', () => ({
  api: { imageGenerationModels: vi.fn() },
}))

const model: ImageGenerationModel = {
  config_id: 7,
  name: '测试生图模型',
  model: 'test-image-model',
  model_type: 'seedream_5_lite',
  concurrency: 3,
  capabilities: {
    clarities: ['1.5K'],
    aspect_ratios: ['16:9'],
    output_formats: ['png'],
    generation_counts: [1],
    default_clarity: '1.5K',
    default_aspect_ratio: '16:9',
    default_output_format: 'png',
    default_generation_count: 1,
  },
}

const assets: Asset[] = [
  { id: 1, novel_id: 9, asset_type: AssetTypeEnum.PERSON, canonical_name: '角色甲', created_at: '', updated_at: '' },
  { id: 2, novel_id: 9, asset_type: AssetTypeEnum.SCENE, canonical_name: '场景甲', created_at: '', updated_at: '' },
  { id: 3, novel_id: 9, asset_type: AssetTypeEnum.ITEM, canonical_name: '道具甲', created_at: '', updated_at: '' },
  { id: 4, novel_id: 9, asset_type: AssetTypeEnum.PERSON, canonical_name: '已完成角色', main_image: '/done.png', created_at: '', updated_at: '' },
]

async function mountDialog() {
  const wrapper = mount(AssetBatchGenerateDialog, {
    props: {
      open: false,
      assets,
      generatingIds: new Set<number>(),
      failedIds: new Set<number>(),
    },
    global: { components: { AppButton }, stubs: { Teleport: true } },
  })
  await wrapper.setProps({ open: true })
  await flushPromises()
  return wrapper
}

describe('AssetBatchGenerateDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.imageGenerationModels).mockResolvedValue({ code: 0, message: 'ok', data: [model] })
  })

  it('可同时整类选择角色、场景和道具并一次提交', async () => {
    const wrapper = await mountDialog()

    const typeButtons = wrapper.findAll('.batch-type')
    expect(typeButtons).toHaveLength(3)
    for (const button of typeButtons) await button.get('input').setValue(true)

    expect(wrapper.findAll('.batch-asset.is-selected')).toHaveLength(3)
    const submit = wrapper.findAll('button').find(button => button.text().includes('生成 3 个'))
    expect(submit).toBeDefined()
    await submit!.trigger('click')

    expect(wrapper.emitted('generate')?.[0]?.[0]).toMatchObject({
      assetIds: [1, 2, 3],
      modelConfigId: 7,
      concurrency: 3,
    })
  })

  it('全选会跨三种类型选择所有未完成资产', async () => {
    const wrapper = await mountDialog()

    const selectAll = wrapper.findAll('button').find(button => button.text() === '全选')
    expect(selectAll).toBeDefined()
    await selectAll!.trigger('click')

    expect(wrapper.findAll('.batch-asset.is-selected')).toHaveLength(3)
  })

  it('整类选择包含衍生形态，基础形象已完成时仍能单独生成缺图形态', async () => {
    const wrapper = await mountDialog()
    await wrapper.setProps({ assets: [...assets.slice(0, 3), {
      ...assets[3]!, variants: [
        { id: 41, asset_id: 4, name: '少年', images: [], created_at: '', updated_at: '' },
        { id: 42, asset_id: 4, name: '成年', images: ['/adult.png'], created_at: '', updated_at: '' },
      ],
    }] })
    await wrapper.findAll('.batch-type')[0]!.get('input').setValue(true)
    expect(wrapper.text()).toContain('已完成角色 · 少年')
    expect(wrapper.findAll('.batch-asset.is-selected')).toHaveLength(2)
    await wrapper.findAll('button').find(button => button.text().includes('生成 2 个'))!.trigger('click')
    expect(wrapper.emitted('generate')?.[0]?.[0]).toMatchObject({ assetIds: [1], variantIds: [41] })
    const base = wrapper.findAll('.batch-asset').find(row => row.text().includes('已完成角色') && row.text().includes('基础形象'))!
    const completed = wrapper.findAll('.batch-asset').find(row => row.text().includes('已完成角色 · 成年'))!
    expect(base.find('input').attributes('disabled')).toBeDefined()
    expect(completed.find('input').attributes('disabled')).toBeDefined()
  })

  it('全选包含所有缺图形态，并允许取消单个形态', async () => {
    const wrapper = await mountDialog()
    await wrapper.setProps({ assets: [{ ...assets[0]!, variants: [
      { id: 11, asset_id: 1, name: '战斗', images: [], created_at: '', updated_at: '' },
      { id: 12, asset_id: 1, name: '日常', images: [], created_at: '', updated_at: '' },
    ] }] })
    await wrapper.findAll('button').find(button => button.text() === '全选')!.trigger('click')
    expect(wrapper.findAll('.batch-asset.is-selected')).toHaveLength(3)
    await wrapper.findAll('.batch-asset input')[1]!.setValue(false)
    await wrapper.findAll('button').find(button => button.text().includes('生成 2 个'))!.trigger('click')
    expect(wrapper.emitted('generate')?.[0]?.[0]).toMatchObject({ assetIds: [1], variantIds: [12] })
  })

  it('只禁用正在生成的目标，其他缺图形态仍可选择与重试', async () => {
    const wrapper = await mountDialog()
    await wrapper.setProps({
      assets: [{ ...assets[0]!, variants: [
        { id: 11, asset_id: 1, name: '战斗', images: [], created_at: '', updated_at: '' },
        { id: 12, asset_id: 1, name: '日常', images: [], created_at: '', updated_at: '' },
      ] }], generatingIds: new Set([1]), generatingTargets: new Set(['variant:11']), failedTargets: new Set(['variant:12']),
    })
    await wrapper.findAll('.batch-type')[0]!.get('input').setValue(true)
    expect(wrapper.findAll('.batch-asset.is-selected')).toHaveLength(2)
    const rows = wrapper.findAll('.batch-asset')
    expect(rows[1]!.text()).toContain('生成中')
    expect(rows[1]!.get('input').attributes('disabled')).toBeDefined()
    expect(rows[2]!.text()).toContain('上次失败，可重试')
    await rows[0]!.get('input').setValue(false)
    expect(wrapper.get('.batch-type input').element).toHaveProperty('indeterminate', true)
    await wrapper.findAll('button').find(button => button.text().includes('生成 1 个'))!.trigger('click')
    expect(wrapper.emitted('generate')?.[0]?.[0]).toMatchObject({ assetIds: [], variantIds: [12] })
  })
})
