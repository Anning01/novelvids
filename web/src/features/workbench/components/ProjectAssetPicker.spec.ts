import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import { AssetTypeEnum } from '@/types'
import ProjectAssetPicker from './ProjectAssetPicker.vue'

vi.mock('@/api', () => ({
  api: {
    digitalHumans: vi.fn(),
    projectAssetLibrary: vi.fn(),
    publicAssetLibrary: vi.fn(),
  },
}))

const digitalHumansMock = vi.mocked(api.digitalHumans)
const projectAssetLibraryMock = vi.mocked(api.projectAssetLibrary)
const publicAssetLibraryMock = vi.mocked(api.publicAssetLibrary)
const pagination = { total: 1, page: 1, page_size: 24, pages: 1 }

beforeEach(() => {
  digitalHumansMock.mockResolvedValue({
    code: 0,
    message: 'ok',
    data: {
      items: [{ id: 7, country: '中国', age: 28, gender: '女', occupation: '演员', asset_id: 'human-7', image_url: '/human-7.png', is_active: true, created_at: '', updated_at: '' }],
      pagination,
    },
  })
  projectAssetLibraryMock.mockResolvedValue({
    code: 0,
    message: 'ok',
    data: {
      items: [
        { id: 31, novel_id: 9, asset_type: AssetTypeEnum.PERSON, canonical_name: '项目人物', created_at: '', updated_at: '' },
        { id: 32, novel_id: 9, asset_type: AssetTypeEnum.SCENE, canonical_name: '不应显示的场景', created_at: '', updated_at: '' },
      ],
      pagination,
    },
  })
  publicAssetLibraryMock.mockResolvedValue({ code: 0, message: 'ok', data: { items: [], pagination } })
})

function mountPicker(assetType = AssetTypeEnum.PERSON) {
  return mount(ProjectAssetPicker, {
    props: {
      open: true,
      novelId: 9,
      assetType,
      excludedIds: [],
    },
    global: {
      stubs: {
        Teleport: true,
        AppButton: { template: '<button type="button"><slot /></button>' },
      },
    },
  })
}

it('loads public people and project assets only for the selected node type', async () => {
  const wrapper = mountPicker()
  await flushPromises()

  expect(digitalHumansMock).toHaveBeenCalledWith(1, '')
  expect(wrapper.text()).toContain('演员')
  expect(wrapper.text()).toContain('公共资产')
  expect(wrapper.text()).toContain('项目资产')

  await wrapper.findAll('button').find(button => button.text().includes('项目资产'))!.trigger('click')
  await flushPromises()

  expect(projectAssetLibraryMock).toHaveBeenCalledWith(9, 1, '', 24, AssetTypeEnum.PERSON)
  expect(wrapper.text()).toContain('项目人物')
  expect(wrapper.text()).not.toContain('不应显示的场景')

  await wrapper.findAll('button').find(button => button.text().includes('项目人物'))!.trigger('click')
  expect(wrapper.emitted('choose')?.[0]?.[0]).toMatchObject({ scope: 'project', asset: { id: 31 } })
})

it('queries public scene assets with the scene type after switching scope', async () => {
  const wrapper = mountPicker(AssetTypeEnum.SCENE)
  await flushPromises()

  expect(projectAssetLibraryMock).toHaveBeenCalledWith(9, 1, '', 24, AssetTypeEnum.SCENE)
  await wrapper.findAll('button').find(button => button.text().includes('公共资产'))!.trigger('click')
  await flushPromises()

  expect(publicAssetLibraryMock).toHaveBeenCalledWith(AssetTypeEnum.SCENE, 1, '')
  expect(wrapper.find('[aria-label="搜索公共场景资产"]').exists()).toBe(true)
})
