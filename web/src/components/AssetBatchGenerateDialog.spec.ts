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
    for (const button of typeButtons) await button.trigger('click')

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
})
