import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import ImageAnnotationEditor from './ImageAnnotationEditor.vue'

const context = { clearRect: vi.fn(), drawImage: vi.fn(), save: vi.fn(), restore: vi.fn(),
  beginPath: vi.fn(), strokeRect: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(),
  closePath: vi.fn(), fill: vi.fn(), ellipse: vi.fn() }
const createObjectURL = vi.fn()
const revokeObjectURL = vi.fn()

class DecodedImage {
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  complete = true
  naturalWidth = 800
  naturalHeight = 500
  private value = ''
  get src() { return this.value }
  set src(value: string) {
    this.value = value
    if (value) queueMicrotask(() => this.onload?.())
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  createObjectURL.mockImplementation(() => `blob:annotation-${createObjectURL.mock.calls.length}`)
  vi.stubGlobal('Image', DecodedImage)
  vi.stubGlobal('URL', class extends URL {
    static createObjectURL = createObjectURL
    static revokeObjectURL = revokeObjectURL
  })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(new Uint8Array([137, 80, 78, 71]), {
    headers: { 'Content-Type': 'image/png' },
  })))
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as unknown as CanvasRenderingContext2D)
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(callback => callback(new Blob(['annotated'], { type: 'image/png' })))
})
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); delete document.documentElement.dataset.appTheme })

it.each(['light', 'dark'])('reloads the original with CORS and exports a marked PNG in %s mode', async theme => {
  document.documentElement.dataset.appTheme = theme
  const url = 'https://cdn.example.com/original.png?signature=keep-intact'
  const wrapper = mount(ImageAnnotationEditor, { props: { open: true, imageUrl: url }, global: { stubs: { Teleport: true } } })
  await flushPromises()
  expect(fetch).toHaveBeenCalledWith(url, { mode: 'cors', cache: 'reload', signal: expect.any(AbortSignal) })
  expect(createObjectURL).toHaveBeenCalledOnce()
  expect(context.drawImage).toHaveBeenCalled()
  expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  const canvas = wrapper.get('canvas').element
  canvas.setPointerCapture = vi.fn()
  canvas.releasePointerCapture = vi.fn()
  vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 0, 800, 500))
  for (const [type, clientX, clientY] of [['pointerdown', 10, 10], ['pointermove', 100, 100], ['pointerup', 100, 100]] as const) {
    const event = new MouseEvent(type, { clientX, clientY, bubbles: true })
    Object.defineProperty(event, 'pointerId', { value: 1 })
    canvas.dispatchEvent(event)
  }
  await wrapper.vm.$nextTick()
  await wrapper.get('.image-annotation__panel > footer button').trigger('click')
  expect(wrapper.emitted('save')?.[0]).toEqual([expect.any(Blob)])
  wrapper.unmount()
  expect(revokeObjectURL).toHaveBeenCalledWith('blob:annotation-1')
})

it('reports inaccessible images and keeps saving disabled', async () => {
  vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 403 }))
  const wrapper = mount(ImageAnnotationEditor, { props: { open: true, imageUrl: 'https://cdn.example.com/missing.png' }, global: { stubs: { Teleport: true } } })
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('图片加载失败')
  expect(wrapper.get('footer button').attributes('disabled')).toBeDefined()
  expect(createObjectURL).not.toHaveBeenCalled()
})

it('aborts closed loads and never decodes their late results', async () => {
  let finish!: (response: Response) => void
  vi.mocked(fetch).mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const wrapper = mount(ImageAnnotationEditor, { props: { open: true, imageUrl: 'https://cdn.example.com/slow.png' }, global: { stubs: { Teleport: true } } })
  await flushPromises()
  const signal = vi.mocked(fetch).mock.calls[0]?.[1]?.signal
  await wrapper.setProps({ open: false })
  expect(signal?.aborted).toBe(true)
  finish(new Response('late image'))
  await flushPromises()
  expect(createObjectURL).not.toHaveBeenCalled()
})

it('keeps caller-owned blob URLs usable after closing the editor', async () => {
  const wrapper = mount(ImageAnnotationEditor, { props: { open: true, imageUrl: 'blob:uploaded-preview' }, global: { stubs: { Teleport: true } } })
  await flushPromises()
  expect(fetch).not.toHaveBeenCalled()
  expect(context.drawImage).toHaveBeenCalled()
  wrapper.unmount()
  expect(revokeObjectURL).not.toHaveBeenCalled()
})

it('uses elliptical grid density per drawing instead of rectangular grid lines', async () => {
  const wrapper = mount(ImageAnnotationEditor, { props: { open: true, imageUrl: 'blob:preview' }, global: { stubs: { Teleport: true } } })
  await flushPromises()
  expect(wrapper.find('[aria-label="网格密度"]').exists()).toBe(false)
  await wrapper.findAll('button').find(button => button.text() === '网格')!.trigger('click')
  for (const [density, expectedLines] of [[8, 14], [24, 60]] as const) {
    await wrapper.get('[aria-label="网格密度"]').setValue(density)
    const canvas = wrapper.get('canvas').element
    canvas.setPointerCapture = vi.fn()
    canvas.releasePointerCapture = vi.fn()
    vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 0, 800, 500))
    for (const [type, x, y] of [['pointerdown', 100, 40], ['pointermove', 300, 400], ['pointerup', 300, 400]] as const) {
      if (type === 'pointerup') context.stroke.mockClear()
      const event = new MouseEvent(type, { bubbles: true, clientX: x, clientY: y })
      Object.defineProperty(event, 'pointerId', { value: 1 })
      canvas.dispatchEvent(event)
    }
    expect(context.stroke).toHaveBeenCalledTimes(expectedLines)
  }
  expect(context.strokeRect).not.toHaveBeenCalled()
  expect(context.ellipse).not.toHaveBeenCalled()
})
