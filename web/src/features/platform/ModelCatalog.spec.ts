import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { setLocale } from '@/i18n'
import AppSelect from '@/components/AppSelect.vue'
import ModelCatalog, { type CatalogModel } from './ModelCatalog.vue'

const models: CatalogModel[] = [
  { id: 'nv-3', name: 'Video 10', kinds: ['video'], pricing: {type:'video',currency:'CNY',prices:{'1080p':5,'480p':2,'4k':8},video_reference_prices:{'480p':1}} },
  { id: 'nv-12', name: 'Image 2', kinds: ['image'], reference_image_urls:true, pricing:{type:'image',currency:'CNY',prices:{'2K':0.2}} },
  { id: 'nv-2', name: 'Text 1', kinds: ['text'], tool_calls:true, pricing:{type:'text',currency:'CNY',input_price_per_1m:2,output_price_per_1m:8} },
]
beforeEach(() => setLocale('zh'))
afterEach(() => { delete document.documentElement.dataset.appTheme; vi.unstubAllGlobals() })

it.each(['light','dark'])('groups models and sorts results without changing configured tariffs (%s)', async theme => {
  document.documentElement.dataset.appTheme = theme
  const w = mount(ModelCatalog, {props:{models}})
  const ids = () => w.findAll('.model-card').map(card => card.attributes('data-model-id'))
  expect(ids()).toEqual(['nv-12','nv-3','nv-2'])
  expect(w.findAll('.catalog-group-title').map(heading => heading.text())).toEqual(['图片1','视频1','文本1'])
  w.getComponent(AppSelect).vm.$emit('update:modelValue','newest')
  await flushPromises()
  expect(ids()).toEqual(['nv-12','nv-3','nv-2'])
  w.getComponent(AppSelect).vm.$emit('update:modelValue','name-desc')
  await flushPromises()
  expect(ids()).toEqual(['nv-3','nv-2','nv-12'])
  await w.get('input[type="search"]').setValue('NV-12')
  expect(ids()).toEqual(['nv-12'])
  await w.get('input[type="search"]').setValue('not-found')
  expect(w.text()).toContain('没有找到匹配的模型')
  await w.get('.catalog-empty button').trigger('click')
  expect(ids()).toHaveLength(3)
  const video = w.get('[data-model-id="nv-3"]')
  expect(video.get('details').attributes('open')).toBeUndefined()
  expect(video.get('details').text()).toContain('参考视频 · 480p')
  expect(video.get('details').text()).toContain('¥1 / 百万 token')
  expect(video.findAll('.model-prices')[0]!.findAll('dt').map(label => label.text())).toEqual(['480p','1080p','4k'])
  expect(models[0]!.pricing.prices).toEqual({'1080p':5,'480p':2,'4k':8})
  w.unmount()
})

it('copies the exact model ID and reports success on its button', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal('navigator',{clipboard:{writeText}})
  const w = mount(ModelCatalog, {props:{models}})
  await w.get('[aria-label="复制模型 ID nv-12"]').trigger('click')
  await flushPromises()
  expect(writeText).toHaveBeenCalledWith('nv-12')
  expect(w.find('[aria-label="复制模型 ID nv-12"] .lucide-check').exists()).toBe(true)
  w.unmount()
})

it('filters models using sidebar series, resolutions, features and switches view modes', async () => {
  const richModels: CatalogModel[] = [
    { id: 'nv-1', name: 'doubao-seedance-2-0-fast', kinds: ['video'], video_model_type: 'doubao-seedance-2-0-fast', pricing: { type: 'video', currency: 'CNY', prices: { '480p': 37, '720p': 37 } } },
    { id: 'nv-2', name: 'doubao-seedream-5-0-flash', kinds: ['image'], image_model_type: 'doubao-seedream-5-0-flash', reference_image_urls: true, pricing: { type: 'image', currency: 'CNY', prices: { '1K': 0.12, '2K': 0.12 } } },
    { id: 'nv-3', name: 'doubao-seedance-2-0-mini (优惠渠道)', kinds: ['video'], video_model_type: 'doubao-seedance-2-0-mini', pricing: { type: 'video', currency: 'CNY', discount: 0.6, prices: { '480p': 23, '720p': 23 } } },
    { id: 'nv-4', name: 'custom-text-model', kinds: ['text'], pricing: { type: 'text', currency: 'CNY', input_price_per_1m: 1 } },
  ]
  const w = mount(ModelCatalog, { props: { models: richModels } })
  const ids = () => w.findAll('.model-card').map(card => card.attributes('data-model-id'))

  // Initial models: sorted by lower multiplier first (nv-3 discount 0.6 precedes nv-1 no discount)
  expect(ids()).toEqual(['nv-2', 'nv-3', 'nv-1', 'nv-4'])

  // Verify visual impact discount badge and standard price badge
  expect(w.get('[data-model-id="nv-3"] .official-discount-badge').text()).toContain('官方价')
  expect(w.get('[data-model-id="nv-3"] .official-discount-badge').text()).toContain('6')
  expect(w.get('[data-model-id="nv-3"] .official-discount-badge').text()).toContain('折')
  expect(w.get('[data-model-id="nv-3"] .official-discount-badge').text()).toContain('×0.6')
  expect(w.get('[data-model-id="nv-1"] .standard-pricing-badge').text()).toContain('官方标准价')

  // Filter by series Seedance
  const seedanceCheck = w.findAll('.sidebar-checkbox-label').find(l => l.text().includes('Seedance'))
  expect(seedanceCheck).toBeDefined()
  await seedanceCheck!.get('input').setValue(true)
  await flushPromises()
  expect(ids()).toEqual(['nv-3', 'nv-1'])

  // Filter by feature 优惠渠道
  const discountCheck = w.findAll('.sidebar-checkbox-label').find(l => l.text().includes('优惠渠道'))
  expect(discountCheck).toBeDefined()
  await discountCheck!.get('input').setValue(true)
  await flushPromises()
  expect(ids()).toEqual(['nv-3'])

  // Reset sidebar filters
  await w.get('.reset-filters-btn').trigger('click')
  await flushPromises()
  expect(ids()).toEqual(['nv-2', 'nv-3', 'nv-1', 'nv-4'])

  // Switch view mode to compact and list
  expect(w.find('.catalog.is-grid').exists()).toBe(true)
  await w.get('button[title="紧凑网格视图"]').trigger('click')
  await flushPromises()
  expect(w.find('.catalog.is-compact').exists()).toBe(true)

  await w.get('button[title="列表视图"]').trigger('click')
  await flushPromises()
  expect(w.find('.catalog.is-list').exists()).toBe(true)

  // Action button triggers doc navigation
  const actionBtn = w.get('[data-model-id="nv-1"] .model-action-btn')
  await actionBtn.trigger('click')
  expect(location.hash).toContain('/platform/docs?model=nv-1')

  w.unmount()
})
