import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { unref } from 'vue'
import { expect, it, vi } from 'vitest'
import type { Asset, ImageGenerationModel } from '@/types'
import { AssetTypeEnum } from '@/types'
import { createWorkbenchPromptActionRegistry, workbenchPromptActionRegistryKey } from '../prompt/promptActionRegistry'
import { useWorkbenchStore } from '../store/workbenchStore'
import AssetNode from './AssetNode.vue'

it('uses one available model for parameters, price and generation after reloading an asset with a retired model', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useWorkbenchStore()
  vi.spyOn(store, 'assetGenerationReferenceImages').mockReturnValue(['/shared.png', '/additional.png'])
  const save = vi.spyOn(store, 'saveAsset').mockResolvedValue(undefined)
  const generate = vi.spyOn(store, 'generateAsset').mockResolvedValue(undefined)
  const registry = createWorkbenchPromptActionRegistry()
  const asset: Asset = { id: 9, novel_id: 1, canonical_name: '角色', asset_type: AssetTypeEnum.PERSON,
    metadata: { model_config_id: 999, generation_reference_images: ['/shared.png'] }, created_at: '', updated_at: '' }
  const model: ImageGenerationModel = {
    config_id: 2, name: '生图模型', model: 'image', model_type: 'seedream_5_5', concurrency: 1,
    pricing: { type: 'image', currency: 'CNY', billing_unit: 'pixel_tier', prices: {low: .13, high_capped: .23},
      input_image: { first_free: 0, price_per_image: .05 } },
    capabilities: { clarities: ['1K','2K'], aspect_ratios: ['16:9','9:16'], output_formats: ['png','jpeg'], generation_counts: [1],
      default_clarity: '1K', default_aspect_ratio: '16:9', default_output_format: 'png', default_generation_count: 1,
      sizes: { '1K': ['1424x800','800x1424'], '2K':['2816x1584','1584x2816'] } },
  }
  const data = { asset, imageModelOptions: [model], project_defaults: { aspectRatio: '16:9' }, generate_capability: true }
  const wrapper = shallowMount(AssetNode, { props: { id: 'asset-9', type: 'asset', data } as never,
    global: { plugins: [pinia], provide: { [workbenchPromptActionRegistryKey as symbol]: registry } } })
  try {
    await wrapper.setProps({ data: { ...data, asset: { ...asset }, project_defaults: { ...data.project_defaults } } })
    const action = registry.actions.get('asset-9')![0]!
    const [picker, parameters] = action.controls!
    expect(unref(picker!.modelValue)).toBe(2)
    expect(unref(parameters!.props)?.capabilities).toEqual(model.capabilities)
    expect(unref(action.cost)).toBeCloseTo(.23)
    parameters!.updateModelValue({ aspectRatio: '9:16', clarity: '2K', outputFormat: 'jpeg', generationCount: 1 })
    await flushPromises()
    expect(unref(action.cost)).toBeCloseTo(.33)
    await action.run()
    expect(save).toHaveBeenCalledWith(9, expect.objectContaining({ metadata: expect.objectContaining(
      { model_config_id: 2, aspect_ratio: '9:16', clarity: '2K', output_format: 'jpeg' }) }))
    expect(generate).toHaveBeenCalledWith(9, undefined)
    await wrapper.setProps({ data: { ...data, imageModelOptions: [] } })
    expect(unref(action.enabled)).toBe(false)
    expect(unref(action.cost)).toBeNaN()
  } finally { wrapper.unmount() }
})
