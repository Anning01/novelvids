import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import { useWorkbenchStore } from './workbenchStore'

vi.mock('@/api', () => ({
  api: { upload: vi.fn() },
  sleep: vi.fn(),
}))

const uploadMock = vi.mocked(api.upload)
let store: ReturnType<typeof useWorkbenchStore>

beforeEach(() => {
  setActivePinia(createPinia())
  store = useWorkbenchStore()
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
