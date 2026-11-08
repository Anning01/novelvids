import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import type { Asset, AssetVariant } from '@/types'
import { AssetTypeEnum } from '@/types'
import { flushPromises } from '@vue/test-utils'
import { assetNodeKey, assetForWorkbenchNode, assetSelectedImageCandidates } from '../config/assetConfig'
import { useWorkbenchStore } from './workbenchStore'

vi.mock('@/api', () => ({
  api: { updateAsset: vi.fn(), updateAssetVariant: vi.fn(), upload: vi.fn(), createAssetVariant: vi.fn(), deleteAssetVariant: vi.fn(), deleteAsset: vi.fn(), updateScene: vi.fn() },
  mediaUrl: (path?: string | null) => path || '',
  persistedMediaRef: (uploaded: { filename: string }) => `/media/${uploaded.filename}`,
}))

let store: ReturnType<typeof useWorkbenchStore>
let base: Asset
let variant: AssetVariant
beforeEach(() => {
  vi.clearAllMocks()
  setActivePinia(createPinia())
  store = useWorkbenchStore()
  variant = { id: 7, asset_id: 1, name: '变装', base_traits: '衍生设定', images: ['/variant.png'],
    metadata: {}, created_at: '', updated_at: '' }
  base = { id: 1, novel_id: 9, asset_type: AssetTypeEnum.PERSON, canonical_name: '角色',
    base_traits: '基础设定', main_image: '/base.png', metadata: { workbenchImage: { width: 320, height: 180 } },
    variants: [variant], created_at: '', updated_at: '' }
  store.assets = [base]
  vi.spyOn(store, 'rebuildGraph').mockImplementation(() => {})
  vi.mocked(api.updateAssetVariant).mockImplementation(async (_assetId, _variantId, patch) => ({
    code: 0, message: 'ok', data: { ...variant, ...patch },
  }))
})

function graph() {
  vi.mocked(store.rebuildGraph).mockRestore()
  store.chapterId = 10
  store.novelId = 9
  store.chapter = { id: 10, novel_id: 9, number: 1, name: '当前章', created_at: '', updated_at: '' }
  store.scenes = [{ id: 20, chapter_id: 10, sequence: 1, prompt: '', asset_ids: [1], metadata: {}, created_at: '', updated_at: '' }]
  store.assets = [{ ...base, variants: [variant, { ...variant, id: 8, name: '成年', images: ['/adult.png'] }] }]
  vi.mocked(api.updateScene).mockImplementation(async (_id, patch) => ({ code: 0, message: 'ok', data: { ...store.scenes[0]!, ...patch } }))
  store.rebuildGraph()
}

it('adds variant nodes alongside the unchanged base and keeps separate reference images', () => {
  graph()
  expect(store.nodes.filter(node => node.kind === 'asset').map(node => node.key))
    .toEqual(['asset-1', 'asset-1-variant-7', 'asset-1-variant-8'])
  const images = [undefined, 7, 8].map(id => assetSelectedImageCandidates(assetForWorkbenchNode(store.nodeByKey(assetNodeKey(1, id))!)!)[0]?.url)
  expect(images).toEqual(['/base.png', '/variant.png', '/adult.png'])
  expect(store.connectMediaNode('asset-1-variant-7', 'shot-20')).toBe(true)
  expect(store.connectMediaNode('asset-1-variant-8', 'shot-20')).toBe(true)
  expect(store.connectMediaNode('asset-1-variant-7', 'shot-20')).toBe(false)
  store.rebuildGraph()
  expect(store.edges.filter(edge => edge.target === 'shot-20').map(edge => edge.source))
    .toEqual(['asset-1', 'asset-1-variant-7', 'asset-1-variant-8'])
  store.persistLayout()
  store.mediaEdges = []
  store.loadSavedLayout()
  expect(store.edges.filter(edge => edge.target === 'shot-20')).toHaveLength(3)
})

it('creates a new empty node without moving or replacing the existing base card', async () => {
  graph()
  const original = store.nodeByKey('asset-1')!
  original.position = { x: 100, y: 200 }
  vi.mocked(api.createAssetVariant).mockResolvedValue({ code: 0, message: 'ok', data: { ...variant, id: 9, name: '新形态', images: [] } })
  await store.createAssetVariant(1, { name: '新形态' })
  expect(store.nodeByKey('asset-1')?.position).toEqual({ x: 100, y: 200 })
  expect(assetForWorkbenchNode(store.nodeByKey('asset-1')!)?.main_image).toBe('/base.png')
  expect(assetSelectedImageCandidates(assetForWorkbenchNode(store.nodeByKey('asset-1-variant-9')!)!)).toEqual([])
  expect(store.selectedNodeKeys).toEqual(['asset-1-variant-9'])
})

it('places newly exposed variants below existing cards when restoring an older layout', () => {
  graph()
  localStorage.setItem(store.layoutKey(), JSON.stringify({ version: 2, viewport: { x: 0, y: 0, zoom: 1 },
    nodes: { 'asset-1': { position: { x: 800, y: 1400 }, size: { width: 520, height: 300 }, zIndex: 1, ui: {} } },
    manualNodes: [], manualEdges: [] }))
  store.loadSavedLayout()
  expect(store.nodeByKey('asset-1')?.position).toEqual({ x: 800, y: 1400 })
  const first = store.nodeByKey('asset-1-variant-7')!
  const second = store.nodeByKey('asset-1-variant-8')!
  expect(first.position.x).toBe(800)
  expect(first.position.y).toBeGreaterThan(1700)
  expect(second.position.y).toBeGreaterThan(first.position.y + 320)
})

it('deletes only the selected variant, keeping the base and sibling nodes', async () => {
  graph()
  vi.mocked(api.deleteAssetVariant).mockResolvedValue({ code: 0, message: 'ok', data: null })
  await store.deleteNodeKeys(['asset-1-variant-7'])
  expect(api.deleteAssetVariant).toHaveBeenCalledWith(1, 7)
  expect(api.deleteAsset).not.toHaveBeenCalled()
  expect(store.nodeByKey('asset-1')).toBeTruthy()
  expect(store.nodeByKey('asset-1-variant-8')).toBeTruthy()
  expect(store.nodeByKey('asset-1-variant-7')).toBeUndefined()
  expect(store.assets[0]?.main_image).toBe('/base.png')
})

it('removes one reference while retaining another form of the same actor', async () => {
  graph()
  store.connectMediaNode('asset-1-variant-7', 'shot-20')
  const primary = store.edges.find(edge => edge.source === 'asset-1' && edge.target === 'shot-20')!
  await store.removeReferenceEdge(primary.key)
  await flushPromises()
  expect(store.scenes[0]?.asset_ids).toEqual([1])
  expect(store.edges.filter(edge => edge.target === 'shot-20').map(edge => edge.source)).toEqual(['asset-1-variant-7'])
})

it('adds the base to a variant-only shot without discarding the existing variant reference', async () => {
  graph()
  store.scenes = [{ ...store.scenes[0]!, metadata: { asset_variant_ids: { '1': 7 } } }]
  store.rebuildGraph()
  expect(store.edges.filter(edge => edge.target === 'shot-20').map(edge => edge.source)).toEqual(['asset-1-variant-7'])
  expect(store.connectMediaNode('asset-1', 'shot-20')).toBe(true)
  await flushPromises()
  expect(store.scenes[0]?.metadata?.asset_variant_ids).toEqual({ '1': null })
  expect(store.edges.filter(edge => edge.target === 'shot-20').map(edge => edge.source)).toEqual(['asset-1', 'asset-1-variant-7'])
})

it('saves variant prompts using the variant endpoint and its own version precondition', async () => {
  await store.saveAssetVariant(1, 7, { base_traits: '新的衍生设定' })
  expect(api.updateAssetVariant).toHaveBeenCalledWith(1, 7, { base_traits: '新的衍生设定' }, '衍生设定')
  expect(api.updateAsset).not.toHaveBeenCalled()
  expect(store.assets[0]?.base_traits).toBe('基础设定')
  expect(store.assets[0]?.variants?.[0]?.base_traits).toBe('新的衍生设定')
})

it('stores measured dimensions on the selected variant only', async () => {
  await store.updateAssetImageMetadata(1, { width: 2048, height: 1152 }, 7)
  expect(api.updateAssetVariant).toHaveBeenCalledWith(1, 7,
    { metadata: { workbenchImage: { width: 2048, height: 1152 } } }, undefined)
  expect(store.assets[0]?.metadata).toEqual(base.metadata)
  expect(api.updateAsset).not.toHaveBeenCalled()
})

it('uploads a replacement into variant images without replacing the base photo', async () => {
  vi.mocked(api.upload).mockResolvedValue({ filename: 'replacement.png', original_filename: 'new.png',
    file_path: '/tmp/replacement.png', content_type: 'image/png' })
  await store.replaceAssetImage(1, new File(['image'], 'new.png', { type: 'image/png' }), 7)
  expect(api.updateAssetVariant).toHaveBeenCalledWith(1, 7, expect.objectContaining({
    images: ['/media/replacement.png', '/variant.png'],
    metadata: { workbenchImage: expect.objectContaining({ source: 'upload', annotations: [] }) },
  }), undefined)
  expect(store.assets[0]?.main_image).toBe('/base.png')
  expect(api.updateAsset).not.toHaveBeenCalled()
})

it('never falls back to the base when a selected variant no longer exists', async () => {
  await store.replaceAssetImage(1, new File(['image'], 'new.png'), 999)
  await store.updateAssetImageMetadata(1, { width: 2048, height: 1152 }, 999)
  await store.saveAssetImageAnnotations(1, [], 999)
  expect(api.upload).not.toHaveBeenCalled()
  expect(api.updateAsset).not.toHaveBeenCalled()
  expect(api.updateAssetVariant).not.toHaveBeenCalled()
})
