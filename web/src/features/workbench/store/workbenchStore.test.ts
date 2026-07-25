import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import { AssetTypeEnum, TaskStatusEnum } from '@/types'
import { useWorkbenchStore } from './workbenchStore'

vi.mock('@/api', () => ({
  api: { createAsset: vi.fn(), createScene: vi.fn(), deleteAsset: vi.fn(), updateAsset: vi.fn(), updateScene: vi.fn() },
  sleep: vi.fn(),
}))

const createAssetMock = vi.mocked(api.createAsset)
const createSceneMock = vi.mocked(api.createScene)
const deleteAssetMock = vi.mocked(api.deleteAsset)
const updateAssetMock = vi.mocked(api.updateAsset)
const updateSceneMock = vi.mocked(api.updateScene)
let store: ReturnType<typeof useWorkbenchStore>

beforeEach(() => {
  setActivePinia(createPinia())
  store = useWorkbenchStore()
  store.chapterId = 2162
  store.novelId = 9
})

it('does not leave a shot when createScene rejects', async () => {
  createSceneMock.mockRejectedValueOnce(new Error('network'))

  await expect(store.addShot({ x: 20, y: 30 })).rejects.toThrow('network')
  expect(store.nodes.some(node => node.kind === 'shot')).toBe(false)
})

it('deletes an explicit note key and restores selection through undo and redo', async () => {
  vi.spyOn(Date, 'now')
    .mockReturnValueOnce(1001)
    .mockReturnValueOnce(1002)
  const first = store.addNote({ x: 20, y: 30 })
  const second = store.addNote({ x: 80, y: 90 })
  store.selectNode(second.key)

  await expect(store.deleteNodeKeys([first.key])).resolves.toBe(1)
  expect(store.nodeByKey(first.key)).toBeUndefined()
  expect(store.selectedNodeKeys).toEqual([second.key])

  expect(store.undo()).toBe(true)
  expect(store.nodeByKey(first.key)).toBeTruthy()
  expect(store.selectedNodeKeys).toEqual([second.key])

  expect(store.redo()).toBe(true)
  expect(store.nodeByKey(first.key)).toBeUndefined()
})

it('copies and pastes a note with the copied content selected', async () => {
  vi.spyOn(Date, 'now')
    .mockReturnValueOnce(2001)
    .mockReturnValueOnce(2002)
  const original = store.addNote({ x: 20, y: 30 })
  store.updateManualNodeData(original.key, { content: '复制内容' })
  store.copySelection()

  await store.paste()

  const notes = store.nodes.filter(node => node.kind === 'note')
  expect(notes).toHaveLength(2)
  expect(notes[1]?.data.content).toBe('复制内容')
  expect(store.selectedNodeKeys).toEqual([notes[1]!.key])
})

it('creates, positions, selects, and persists an empty asset', async () => {
  store.chapter = {
    id: 2162,
    novel_id: 9,
    number: 1,
    name: '章节',
    created_at: '2026-07-25T00:00:00.000Z',
    updated_at: '2026-07-25T00:00:00.000Z',
  }
  createAssetMock.mockResolvedValueOnce({
    code: 0,
    message: 'ok',
    data: {
      id: 81,
      novel_id: 9,
      asset_type: AssetTypeEnum.PERSON,
      canonical_name: '资产 1',
      created_at: '2026-07-25T00:00:00.000Z',
      updated_at: '2026-07-25T00:00:00.000Z',
    },
  })
  const persist = vi.spyOn(store, 'persistLayout')

  const created = await store.addEmptyAsset({ x: 120, y: 240 })

  expect(createAssetMock).toHaveBeenCalledWith({
    novel_id: 9,
    asset_type: AssetTypeEnum.PERSON,
    canonical_name: '资产 1',
  })
  expect(created?.position).toEqual({ x: 120, y: 240 })
  expect(store.selectedNodeKeys).toEqual(['asset-81'])
  expect(persist).toHaveBeenCalled()
})

it('promotes a real candidate to the asset main image', async () => {
  const source = {
    id: 82,
    novel_id: 9,
    asset_type: AssetTypeEnum.PERSON,
    canonical_name: '人物',
    main_image: '/old.png',
    angle_image_1: '/candidate.png',
    created_at: '2026-07-25T00:00:00.000Z',
    updated_at: '2026-07-25T00:00:00.000Z',
  }
  store.assets = [source]
  updateAssetMock.mockResolvedValueOnce({
    code: 0,
    message: 'ok',
    data: { ...source, main_image: '/candidate.png' },
  })

  await store.setAssetMainImage(82, '/candidate.png')

  expect(updateAssetMock).toHaveBeenCalledWith(82, { main_image: '/candidate.png' })
  expect(store.assets[0]?.main_image).toBe('/candidate.png')
})

it('deletes an explicit backend asset and its node', async () => {
  const source = {
    id: 83,
    novel_id: 9,
    asset_type: AssetTypeEnum.PERSON,
    canonical_name: '临时资产',
    created_at: '2026-07-25T00:00:00.000Z',
    updated_at: '2026-07-25T00:00:00.000Z',
  }
  store.assets = [source]
  store.nodes = [{
    id: 83,
    key: 'asset-83',
    kind: 'asset',
    backendKind: 'asset',
    title: '临时资产',
    position: { x: 0, y: 0 },
    size: null,
    zIndex: 1,
    activeVersionId: null,
    status: 'ready',
    data: { asset: source, ui: {} },
    createdAt: source.created_at,
    updatedAt: source.updated_at,
  }]
  deleteAssetMock.mockResolvedValueOnce({ code: 0, message: 'ok', data: null })

  await expect(store.deleteNodeKeys(['asset-83'])).resolves.toBe(1)

  expect(deleteAssetMock).toHaveBeenCalledWith(83)
  expect(store.assets).toEqual([])
  expect(store.nodeByKey('asset-83')).toBeUndefined()
})

it('persists the active video version without discarding scene metadata', async () => {
  const source = {
    id: 10,
    chapter_id: 2162,
    sequence: 1,
    metadata: { source: 'storyboard', workbench: { aspectRatio: '9:16' } },
    created_at: '2026-07-25T00:00:00.000Z',
    updated_at: '2026-07-25T00:00:00.000Z',
  }
  store.scenes = [source]
  store.videos[10] = [{
    id: 91,
    scene_id: 10,
    model_type: 1,
    status: TaskStatusEnum.COMPLETED,
    created_at: '2026-07-25T00:00:00.000Z',
    updated_at: '2026-07-25T00:00:00.000Z',
  }]
  updateSceneMock.mockResolvedValueOnce({
    code: 0,
    message: 'ok',
    data: {
      ...source,
      metadata: {
        source: 'storyboard',
        workbench: { aspectRatio: '9:16', activeVideoId: 91 },
      },
    },
  })

  await store.setActiveVideo(10, 91)

  expect(updateSceneMock).toHaveBeenCalledWith(10, {
    metadata: {
      source: 'storyboard',
      workbench: { aspectRatio: '9:16', activeVideoId: 91 },
    },
  })
  expect(store.scenes[0]?.metadata?.workbench).toMatchObject({ activeVideoId: 91 })
})
