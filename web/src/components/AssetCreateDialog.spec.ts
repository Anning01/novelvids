import { flushPromises, mount } from '@vue/test-utils'
import { parse } from '@vue/compiler-sfc'
import { expect, it, vi } from 'vitest'
import { api } from '@/api'
import { AssetTypeEnum, type Asset, type DigitalHuman, type PaginationResponse } from '@/types'
import AppButton from './AppButton.vue'
import AssetCreateDialog from './AssetCreateDialog.vue'
import assetDialogSource from './AssetCreateDialog.vue?raw'

vi.mock('@/api', () => ({
  api: {
    configs: vi.fn(),
    digitalHumans: vi.fn(),
    assetLibrary: vi.fn(),
    asset: vi.fn(),
    referencePromptPreview: vi.fn(),
  },
}))

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
  vi.mocked(api.configs).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: { items: [], pagination: { total: 0, page: 1, page_size: 24, pages: 0 } },
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

  expect(wrapper.get('textarea').element.value).toContain('上半身正面平视特写')
  expect(wrapper.get('textarea').element.value).not.toContain(editedAsset.description)

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
  vi.mocked(api.configs).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: { items: [], pagination: { total: 0, page: 1, page_size: 24, pages: 0 } },
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
