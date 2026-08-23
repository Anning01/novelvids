import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { parse } from '@vue/compiler-sfc'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import AppButton from '@/components/AppButton.vue'
import AssetBatchGenerateDialog from '@/components/AssetBatchGenerateDialog.vue'
import AssetCreateDialog from '@/components/AssetCreateDialog.vue'
import { AssetTypeEnum, TaskStatusEnum, type Asset } from '@/types'
import ShortDramaManualPage from './ShortDramaManualPage.vue'
import manualPageSource from './ShortDramaManualPage.vue?raw'

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { projectId: '9' }, query: { chapter: '2162' } }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}))

vi.mock('@/api', () => ({
  api: {
    novel: vi.fn(),
    novelMeta: vi.fn(),
    chapters: vi.fn(),
    chaptersPage: vi.fn(),
    assets: vi.fn(),
    chapter: vi.fn(),
    latestExtraction: vi.fn(),
    updateAsset: vi.fn(),
    generateAsset: vi.fn(),
    task: vi.fn(),
  },
  sleep: vi.fn(),
  statusLabel: vi.fn(() => ''),
}))

const chapter = {
  id: 2162,
  novel_id: 9,
  number: 1,
  name: '厄运之手',
  content: '第一章正文',
  created_at: '2026-08-06T00:00:00.000Z',
  updated_at: '2026-08-06T00:00:00.000Z',
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.novelMeta).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: {
      id: 9,
      name: '厄运之手',
      author: 'Agent 创建',
      description: 'Agent 模式 · 9:16 · 720p · 写实通用',
      content_length: 0,
      created_at: '2026-08-06T00:00:00.000Z',
      updated_at: '2026-08-06T00:00:00.000Z',
    },
  })
  vi.mocked(api.chapter).mockResolvedValue({ code: 0, message: 'ok', data: chapter })
  vi.mocked(api.chapters).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: { items: [chapter], pagination: { total: 1, page: 1, page_size: 30, pages: 1 } },
  })
  vi.mocked(api.latestExtraction).mockResolvedValue({ code: 0, message: 'ok', data: null })
  vi.mocked(api.assets).mockImplementation(async (_novelId, _page, _pageSize, chapterId) => {
    const allAssets = [
        {
          id: 31,
          novel_id: 9,
          asset_type: AssetTypeEnum.PERSON,
          canonical_name: '宫平',
          description: '这是一段很长很长的角色简介，用于验证卡片底部信息超过限制后会显示三个英文点并保持卡片简洁。',
          source_chapters: [1],
          created_at: '2026-08-06T00:00:00.000Z',
          updated_at: '2026-08-06T00:00:00.000Z',
        },
        {
          id: 33,
          novel_id: 9,
          asset_type: AssetTypeEnum.PERSON,
          canonical_name: '云薇子',
          source_chapters: [2],
          created_at: '2026-08-06T00:00:00.000Z',
          updated_at: '2026-08-06T00:00:00.000Z',
        },
        {
          id: 32,
          novel_id: 9,
          asset_type: AssetTypeEnum.SCENE,
          canonical_name: '山门广场',
          source_chapters: [1],
          created_at: '2026-08-06T00:00:00.000Z',
          updated_at: '2026-08-06T00:00:00.000Z',
        },
        {
          id: 34,
          novel_id: 9,
          asset_type: AssetTypeEnum.ITEM,
          canonical_name: '青铜令牌',
          source_chapters: [1],
          created_at: '2026-08-06T00:00:00.000Z',
          updated_at: '2026-08-06T00:00:00.000Z',
        },
      ]
    const items = chapterId ? allAssets.filter(asset => asset.source_chapters.includes(1)) : allAssets
    return {
      code: 0,
      message: 'ok',
      data: {
        items,
        pagination: { total: items.length, page: 1, page_size: 100, pages: 1 },
      },
    }
  })
  vi.mocked(api.updateAsset).mockImplementation(async (assetId, payload) => ({
    code: 0,
    message: 'ok',
    data: {
      id: assetId,
      novel_id: 9,
      asset_type: assetId === 32
        ? AssetTypeEnum.SCENE
        : assetId === 34 ? AssetTypeEnum.ITEM : AssetTypeEnum.PERSON,
      canonical_name: assetId === 32 ? '山门广场' : assetId === 34 ? '青铜令牌' : '宫平',
      source_chapters: [1],
      metadata: payload.metadata,
      created_at: '2026-08-06T00:00:00.000Z',
      updated_at: '2026-08-06T00:00:00.000Z',
    } as Asset,
  }))
  vi.mocked(api.generateAsset).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: {
      id: 'completed-reference-task',
      task_type: 2,
      status: TaskStatusEnum.COMPLETED,
      request_params: {},
      created_at: '2026-08-06T00:00:00.000Z',
      updated_at: '2026-08-06T00:00:00.000Z',
    },
  })
})

async function mountInCurrentChapterScope() {
  const wrapper = mount(ShortDramaManualPage, {
    global: {
      components: { AppButton },
      stubs: {
        AssetCreateDialog: true,
        AssetBatchGenerateDialog: true,
      },
    },
  })
  await flushPromises()
  const currentChapterButton = wrapper.findAll('button').find(button => button.text().includes('当前章节'))
  expect(currentChapterButton).toBeDefined()
  await currentChapterButton!.trigger('click')
  await flushPromises()
  return wrapper
}

it('switches the settings cards and counts between all project assets and current chapter assets', async () => {
  const wrapper = mount(ShortDramaManualPage, {
    global: {
      components: { AppButton },
      stubs: {
        AssetCreateDialog: true,
        AssetBatchGenerateDialog: true,
      },
    },
  })
  await flushPromises()

  expect(wrapper.findAll('.asset-card')).toHaveLength(2)
  const currentChapterButton = wrapper.findAll('button').find(button => button.text().includes('当前章节'))
  expect(currentChapterButton).toBeDefined()
  if (!currentChapterButton) return

  await currentChapterButton.trigger('click')
  await flushPromises()

  const cards = wrapper.findAll('.asset-card')
  expect(cards).toHaveLength(1)
  expect(cards[0].text()).toContain('宫平')
  expect(wrapper.text()).toContain('角色总计 1')
  expect(api.assets).toHaveBeenLastCalledWith(9, 1, 100, 2162)
})

it('uses image-first cards with three hover actions and opens upload in the drawer', async () => {
  const wrapper = await mountInCurrentChapterScope()
  const card = wrapper.get('.asset-card')

  expect(card.findAll('.asset-card-action')).toHaveLength(3)
  expect(card.find('[aria-label*="衍生形态"]').exists()).toBe(false)
  expect(card.get('.asset-visual').classes()).toContain('is-empty')
  expect(card.get('.asset-card-info p').text()).toMatch(/\.\.\.$/)
  const styles = parse(manualPageSource).descriptor.styles.map(block => block.content).join('\n')
  expect(styles).toContain('flex-direction: row-reverse')
  expect(styles).toContain('.asset-visual.is-empty .asset-card-info')
  expect(styles).toContain('opacity: 1')
  expect(styles).toContain('background: var(--app-surface-raised)')
  expect(styles).toContain('rgb(20 22 28 / 94%)')

  await card.get('button[aria-label="为宫平本地上传图片"]').trigger('click')
  await flushPromises()

  const drawer = wrapper.findComponent(AssetCreateDialog)
  expect(drawer.props('open')).toBe(true)
  expect(drawer.props('initialMode')).toBe('upload')
})

it('keeps the current chapter filter when the toolbar refreshes assets', async () => {
  const wrapper = await mountInCurrentChapterScope()
  vi.mocked(api.assets).mockClear()

  await wrapper.get('button[aria-label="刷新"]').trigger('click')
  await flushPromises()

  expect(api.assets).toHaveBeenCalledTimes(1)
  expect(api.assets).toHaveBeenLastCalledWith(9, 1, 100, 2162)
})

it('keeps the current chapter filter after batch generation finishes', async () => {
  const wrapper = await mountInCurrentChapterScope()
  vi.mocked(api.assets).mockClear()

  wrapper.findComponent(AssetBatchGenerateDialog).vm.$emit('generate', {
    assetIds: [31],
    modelConfigId: 2,
    concurrency: 1,
    clarity: '1.5K',
    ratio: '16:9',
    outputFormat: 'png',
    generationCount: 1,
  })
  await flushPromises()

  expect(api.assets).toHaveBeenCalledTimes(1)
  expect(api.assets).toHaveBeenLastCalledWith(9, 1, 100, 2162)
})

it('submits selected assets across character, scene, and prop types in one batch', async () => {
  const wrapper = await mountInCurrentChapterScope()
  vi.mocked(api.updateAsset).mockClear()

  wrapper.findComponent(AssetBatchGenerateDialog).vm.$emit('generate', {
    assetIds: [31, 32, 34],
    modelConfigId: 2,
    concurrency: 3,
    clarity: '1.5K',
    ratio: '16:9',
    outputFormat: 'png',
    generationCount: 1,
  })
  await flushPromises()

  expect(vi.mocked(api.updateAsset).mock.calls.map(([assetId]) => assetId).sort()).toEqual([31, 32, 34])
})

it('shows loading for every queued asset and hides title and description before workers start', async () => {
  const wrapper = await mountInCurrentChapterScope()
  vi.mocked(api.updateAsset).mockImplementation(() => new Promise(() => {}))

  wrapper.findComponent(AssetBatchGenerateDialog).vm.$emit('generate', {
    assetIds: [31, 32, 34],
    modelConfigId: 2,
    concurrency: 1,
    clarity: '1.5K',
    ratio: '16:9',
    outputFormat: 'png',
    generationCount: 1,
  })
  await nextTick()

  const assertVisibleAssetIsLoading = () => {
    expect(wrapper.get('.asset-generating-placeholder').text()).toContain('正在生成参考图')
    expect(wrapper.find('.asset-card-info').exists()).toBe(false)
  }
  assertVisibleAssetIsLoading()

  const sceneTab = wrapper.findAll('.asset-toolbar nav button').find(button => button.text().includes('场景'))
  await sceneTab!.trigger('click')
  await nextTick()
  assertVisibleAssetIsLoading()

  const propTab = wrapper.findAll('.asset-toolbar nav button').find(button => button.text().includes('道具'))
  await propTab!.trigger('click')
  await nextTick()
  assertVisibleAssetIsLoading()
})
