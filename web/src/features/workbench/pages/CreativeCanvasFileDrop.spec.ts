import { flushPromises, shallowMount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import { notice } from '@/shared/notice'
import { droppedMediaKind } from '../interaction/canvasMediaFiles'
import { useWorkbenchStore } from '../store/workbenchStore'
import CreativeCanvas from './CreativeCanvas.vue'

const toCanvasPoint = vi.hoisted(() => vi.fn(() => ({ x: 101, y: -24 })))
vi.mock('../runtime/workbenchFlowRuntime', async original => ({
  ...await original<typeof import('../runtime/workbenchFlowRuntime')>(),
  useWorkbenchFlow: () => ({
    screenToFlowCoordinate: toCanvasPoint,
    findNode: () => undefined,
    getNodes: { value: [] },
    getViewport: () => ({ x: 0, y: 0, zoom: 1 }),
    vueFlowRef: { value: null },
  }),
}))

afterEach(() => { vi.restoreAllMocks(); toCanvasPoint.mockClear() })

function drag(element: Element, type: string, files: File[], types = ['Files']) {
  const transfer = { files, types, dropEffect: 'none' }
  const event = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: 330, clientY: 270 })
  Object.defineProperty(event, 'dataTransfer', { value: transfer })
  element.dispatchEvent(event)
  return { event, transfer }
}

it('uploads a mixed drop at canvas coordinates, continues after errors and ignores internal drags', async () => {
  const pinia = createPinia()
  const store = useWorkbenchStore(pinia)
  vi.spyOn(store, 'load').mockResolvedValue()
  vi.spyOn(api, 'workbenchCapabilities').mockResolvedValue({ data: {} } as never)
  const error = vi.spyOn(notice, 'error').mockImplementation(() => {})
  const wrapper = shallowMount(CreativeCanvas, { props: { novelId: 1, chapterId: 2 }, global: { plugins: [pinia] } })
  try {
    await flushPromises()
    const root = wrapper.get('main').element
    const image = new File(['a'], 'image.PNG')
    const badImage = new File(['b'], 'damaged.webp', { type: 'image/webp' })
    const video = new File(['v'], 'video.mov', { type: 'video/quicktime' })
    const other = new File(['t'], 'notes.txt', { type: 'text/plain' })
    const files = [image, other, badImage, video]
    const imageNode = store.addNote({ x: 101, y: -24 })
    const addImage = vi.spyOn(store, 'uploadImageAsset').mockResolvedValueOnce(imageNode).mockRejectedValueOnce(new Error('network failure'))
    const addVideo = vi.spyOn(store, 'uploadMedia').mockResolvedValue(imageNode)

    expect(drag(root, 'dragover', [], ['text/uri-list']).event.defaultPrevented).toBe(false)
    expect(drag(root, 'dragenter', []).transfer.dropEffect).toBe('copy')
    await flushPromises()
    expect(wrapper.find('.canvas-file-drop').exists()).toBe(true)
    expect(drag(root, 'drop', files).event.defaultPrevented).toBe(true)
    await flushPromises()
    expect(toCanvasPoint).toHaveBeenCalledWith({ x: 330, y: 270 })
    expect(addImage).toHaveBeenNthCalledWith(1, image, { x: 101, y: -24 })
    expect(addImage).toHaveBeenCalledTimes(2)
    const videoDrop = addVideo.mock.calls[0]!
    expect(videoDrop.slice(0, 2)).toEqual(['video_media', video])
    expect(videoDrop[2]?.x).toBeGreaterThan(101)
    expect(videoDrop[2]?.y).toBe(-24)
    expect(error).toHaveBeenCalledWith(expect.stringContaining('notes.txt'))
    expect(error).toHaveBeenCalledWith(expect.stringContaining('damaged.webp'))
    expect(wrapper.find('.canvas-file-drop').exists()).toBe(false)
    expect(wrapper.find('.canvas-upload-status').exists()).toBe(false)
  } finally { wrapper.unmount() }
})

it('accepts file picker formats even when the OS supplies a generic MIME type', () => {
  expect(droppedMediaKind(new File([], 'photo.JPEG', { type: 'application/octet-stream' }))).toBe('image_media')
  expect(droppedMediaKind(new File([], 'clip.MP4'))).toBe('video_media')
  expect(droppedMediaKind(new File([], 'clip.avi', { type: 'video/x-msvideo' }))).toBeNull()
})
