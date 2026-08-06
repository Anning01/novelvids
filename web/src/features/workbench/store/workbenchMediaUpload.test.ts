import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import { AssetTypeEnum } from '@/types'
import { useWorkbenchStore } from './workbenchStore'

vi.mock('@/api', () => ({
  api: { createAsset: vi.fn(), updateAsset: vi.fn(), upload: vi.fn() },
  sleep: vi.fn(),
}))

const createAssetMock = vi.mocked(api.createAsset)
const updateAssetMock = vi.mocked(api.updateAsset)
const uploadMock = vi.mocked(api.upload)
let store: ReturnType<typeof useWorkbenchStore>

beforeEach(() => {
  setActivePinia(createPinia())
  store = useWorkbenchStore()
  store.novelId = 9
  store.chapterId = 2162
  store.chapter = {
    id: 2162,
    novel_id: 9,
    number: 1,
    name: '章节',
    created_at: '2026-07-28T00:00:00.000Z',
    updated_at: '2026-07-28T00:00:00.000Z',
  }
})

it('uploads a new image into a persistent asset node', async () => {
  const file = new File(['image'], 'hero.png', { type: 'image/png' })
  uploadMock.mockResolvedValueOnce({
    filename: 'stored-hero.png',
    original_filename: 'hero.png',
    content_type: 'image/png',
    file_path: '/tmp/stored-hero.png',
  })
  createAssetMock.mockResolvedValueOnce({
    code: 0,
    message: 'ok',
    data: {
      id: 91,
      novel_id: 9,
      asset_type: AssetTypeEnum.ITEM,
      canonical_name: 'hero',
      main_image: '/media/stored-hero.png',
      metadata: {
        workbenchImage: {
          source: 'upload',
          assetTypeExplicit: false,
          filename: 'stored-hero.png',
          originalFilename: 'hero.png',
          mimeType: 'image/png',
          annotations: [],
        },
      },
      created_at: '2026-07-28T00:00:00.000Z',
      updated_at: '2026-07-28T00:00:00.000Z',
    },
  })

  const created = await store.uploadImageAsset(file, { x: 120, y: 240 })

  expect(createAssetMock).toHaveBeenCalledWith({
    novel_id: 9,
    chapter_id: 2162,
    asset_type: AssetTypeEnum.ITEM,
    canonical_name: 'hero',
    main_image: '/media/stored-hero.png',
    metadata: {
      workbenchImage: {
        source: 'upload',
        assetTypeExplicit: false,
        filename: 'stored-hero.png',
        originalFilename: 'hero.png',
        mimeType: 'image/png',
        annotations: [],
      },
    },
  })
  expect(created).toMatchObject({
    key: 'asset-91',
    kind: 'asset',
    title: 'hero',
    position: { x: 120, y: 240 },
  })
  expect(store.manualNodes).toEqual([])
  expect(store.selectedNodeKeys).toEqual(['asset-91'])
})

it('uploads an image before creating a persistent media node', async () => {
  const file = new File(['image'], 'photo.png', { type: 'image/png' })
  uploadMock.mockResolvedValueOnce({
    filename: 'stored-photo.png',
    original_filename: 'photo.png',
    content_type: 'image/png',
    file_path: '/tmp/stored-photo.png',
  })

  const created = await store.uploadMedia('image_media', file, { x: 120, y: 240 })

  expect(uploadMock).toHaveBeenCalledWith(file)
  expect(created).toMatchObject({
    key: expect.stringMatching(/^image-media-\d+$/),
    kind: 'image_media',
    title: 'photo',
    position: { x: 120, y: 240 },
    data: {
      url: '/media/stored-photo.png',
      filename: 'stored-photo.png',
      originalFilename: 'photo.png',
      mimeType: 'image/png',
    },
  })
  expect(store.manualNodes).toEqual([created])
  expect(store.selectedNodeKeys).toEqual([created.key])
  expect(JSON.parse(localStorage.getItem(store.layoutKey()) || '{}').manualNodes).toHaveLength(1)
})

it('does not leave a media node when upload rejects', async () => {
  const file = new File(['video'], 'clip.mp4', { type: 'video/mp4' })
  uploadMock.mockRejectedValueOnce(new Error('network'))

  await expect(store.uploadMedia('video_media', file, { x: 20, y: 30 })).rejects.toThrow('network')

  expect(store.nodes).toEqual([])
  expect(store.manualNodes).toEqual([])
  expect(store.history).toEqual([])
})

it('replaces media in place and clears stale image metadata', async () => {
  const first = {
    filename: 'first.png',
    original_filename: 'first.png',
    content_type: 'image/png',
    file_path: '/tmp/first.png',
  }
  const second = {
    filename: 'second.webp',
    original_filename: 'second.webp',
    content_type: 'image/webp',
    file_path: '/tmp/second.webp',
  }
  uploadMock.mockResolvedValueOnce(first).mockResolvedValueOnce(second)
  const created = await store.uploadMedia('image_media', new File(['first'], 'first.png', { type: 'image/png' }))
  store.updateUploadedMediaMetadata(created.key, { width: 320, height: 180 })
  store.updateManualNodeData(created.key, { annotations: [{ id: 'old' }] })

  const replaced = await store.replaceUploadedMedia(created.key, new File(['second'], 'second.webp', { type: 'image/webp' }))

  expect(replaced?.key).toBe(created.key)
  expect(replaced?.title).toBe('second')
  expect(replaced?.data).toMatchObject({
    url: '/media/second.webp',
    filename: 'second.webp',
    originalFilename: 'second.webp',
    mimeType: 'image/webp',
    annotations: [],
  })
  expect(replaced?.data.width).toBeUndefined()
  expect(store.nodes.filter(node => node.kind === 'image_media')).toHaveLength(1)
})

it('persists annotations only for an uploaded image node', async () => {
  const image = store.addUploadedMedia('image_media', {
    filename: 'photo.png',
    original_filename: 'photo.png',
    content_type: 'image/png',
  })
  const annotation = {
    id: 'rect-1',
    tool: 'rectangle' as const,
    points: [{ x: 0.1, y: 0.1 }, { x: 0.5, y: 0.5 }],
    stroke: '#ff5a5f',
    strokeWidth: 3,
  }

  expect(store.saveImageAnnotations(image.key, [annotation])).toBe(true)
  expect(store.nodeByKey(image.key)?.data.annotations).toEqual([annotation])
  expect(store.saveImageAnnotations('missing', [annotation])).toBe(false)
  expect(JSON.parse(localStorage.getItem(store.layoutKey()) || '{}').manualNodes[0].data.annotations).toEqual([annotation])
})

it('stores image annotations on a backend asset without replacing its generation metadata', async () => {
  const source = {
    id: 92,
    novel_id: 9,
    asset_type: AssetTypeEnum.ITEM,
    canonical_name: '道具',
    main_image: '/media/prop.png',
    metadata: { workbench: { size: '1424x800' } },
    created_at: '2026-07-28T00:00:00.000Z',
    updated_at: '2026-07-28T00:00:00.000Z',
  }
  const annotation = {
    id: 'rect-2',
    tool: 'rectangle' as const,
    points: [{ x: 0.1, y: 0.1 }, { x: 0.5, y: 0.5 }],
    stroke: '#ff5a5f',
    strokeWidth: 3,
  }
  store.assets = [source]
  updateAssetMock.mockResolvedValueOnce({
    code: 0,
    message: 'ok',
    data: {
      ...source,
      metadata: {
        workbench: { size: '1424x800' },
        workbenchImage: { annotations: [annotation] },
      },
    },
  })

  await store.saveAssetImageAnnotations(92, [annotation])

  expect(updateAssetMock).toHaveBeenCalledWith(92, {
    metadata: {
      workbench: { size: '1424x800' },
      workbenchImage: { annotations: [annotation] },
    },
  })
  expect(store.assets[0]?.metadata?.workbench).toEqual({ size: '1424x800' })
})

it('keeps an existing asset type explicit when replacing its image', async () => {
  const source = {
    id: 93,
    novel_id: 9,
    asset_type: AssetTypeEnum.PERSON,
    canonical_name: '主角',
    main_image: '/media/old.png',
    metadata: { workbench: { size: '1024x1024' } },
    created_at: '2026-07-28T00:00:00.000Z',
    updated_at: '2026-07-28T00:00:00.000Z',
  }
  store.assets = [source]
  uploadMock.mockResolvedValueOnce({
    filename: 'new.png',
    original_filename: 'new.png',
    content_type: 'image/png',
    file_path: '/tmp/new.png',
  })
  updateAssetMock.mockResolvedValueOnce({
    code: 0,
    message: 'ok',
    data: {
      ...source,
      main_image: '/media/new.png',
      metadata: {
        workbench: { size: '1024x1024' },
        workbenchImage: {
          source: 'upload',
          assetTypeExplicit: true,
          filename: 'new.png',
          originalFilename: 'new.png',
          mimeType: 'image/png',
          annotations: [],
        },
      },
    },
  })

  await store.replaceAssetImage(93, new File(['new'], 'new.png', { type: 'image/png' }))

  expect(updateAssetMock).toHaveBeenCalledWith(93, {
    main_image: '/media/new.png',
    metadata: {
      workbench: { size: '1024x1024' },
      workbenchImage: {
        source: 'upload',
        assetTypeExplicit: true,
        filename: 'new.png',
        originalFilename: 'new.png',
        mimeType: 'image/png',
        width: undefined,
        height: undefined,
        annotations: [],
      },
    },
  })
})
