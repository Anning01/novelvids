import { DOMWrapper, mount, flushPromises } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import ImageLightbox from './ImageLightbox.vue'

const images = [1, 2, 3].map(n => ({src: `/sheet-${n}.png`, alt: `分镜 ${n}`}))
async function viewer(src = images[1]!.src) {
  const wrapper = mount(ImageLightbox, {attachTo: document.body, props: {open: true, src, alt: '线稿', images}})
  await flushPromises()
  return { wrapper, screen: new DOMWrapper(document.body) }
}
it.each(['light', 'dark'])('opens the selected image and navigates with buttons and arrow keys (%s)', async theme => {
  document.documentElement.dataset.appTheme = theme
  const { wrapper, screen } = await viewer()
  expect(screen.get<HTMLDialogElement>('dialog').element.open).toBe(true)
  expect(screen.get('[role=status]').text()).toContain('2 / 3 · 分镜 2')
  await screen.get('[aria-label="放大图片"]').trigger('click')
  expect(screen.get('output').text()).toBe('125%')
  await screen.get('[aria-label="下一张"]').trigger('click')
  expect(screen.get('[role=status]').text()).toContain('3 / 3 · 分镜 3')
  expect(screen.get('output').text()).toBe('100%')
  expect(screen.get<HTMLButtonElement>('[aria-label="下一张"]').element.disabled).toBe(true)
  await screen.get('dialog').trigger('keydown', {key:'ArrowLeft'})
  expect(screen.get('[role=status]').text()).toContain('2 / 3')
  await screen.get('[aria-label="上一张"]').trigger('click')
  expect(screen.get<HTMLButtonElement>('[aria-label="上一张"]').element.disabled).toBe(true)
  expect(screen.get<HTMLDialogElement>('dialog').element.open).toBe(true)
  await screen.get('[aria-label="关闭大图"]').trigger('click')
  expect(screen.get<HTMLDialogElement>('dialog').element.open).toBe(false)
  await flushPromises()
  expect(wrapper.emitted('close')).toHaveLength(1)
  delete document.documentElement.dataset.appTheme
})
it('updates the selected slide after native horizontal scrolling and keeps browsing after an image error', async () => {
  vi.useFakeTimers()
  const { screen } = await viewer(images[0]!.src)
  const track = screen.get<HTMLElement>('.image-lightbox__track')
  Object.defineProperty(track.element, 'clientWidth', {value: 400})
  track.element.scrollLeft = 400
  await track.trigger('scroll')
  await vi.advanceTimersByTimeAsync(150)
  expect(screen.get('[role=status]').text()).toContain('2 / 3')
  await screen.get('.image-lightbox__stage:not([inert]) img').trigger('error')
  expect(screen.text()).toContain('图片加载失败')
  await screen.get('[aria-label="下一张"]').trigger('click')
  expect(screen.get('.image-lightbox__stage:not([inert]) img').attributes('src')).toBe('/sheet-3.png')
  vi.useRealTimers()
})
it('keeps single-image callers working and reopens at the requested image', async () => {
  const { wrapper, screen } = await viewer()
  await wrapper.setProps({open:false})
  await flushPromises()
  expect(screen.get<HTMLDialogElement>('dialog').element.open).toBe(false)
  await wrapper.setProps({open:true, src:'/single.png', images:[]})
  await flushPromises()
  expect(screen.find('[aria-label="下一张"]').exists()).toBe(false)
  expect(screen.get('img').attributes('src')).toBe('/single.png')
})

it('stays open until the animated close finishes, including repeated cancel requests', async () => {
  const { wrapper, screen } = await viewer()
  await wrapper.setProps({ animated: true })
  const dialog = screen.get<HTMLDialogElement>('dialog')
  let finish!: () => void
  const finished = new Promise<void>(resolve => { finish = resolve })
  const getAnimations = vi.fn(() => [{ finished }])
  Object.defineProperty(dialog.element, 'getAnimations', { value: getAnimations })

  await dialog.trigger('cancel')
  await dialog.trigger('cancel')
  expect(dialog.element.open).toBe(true)
  expect(dialog.find('img').exists()).toBe(true)
  expect(getAnimations).toHaveBeenCalledTimes(1)

  finish()
  await flushPromises()
  expect(dialog.element.open).toBe(false)
  expect(wrapper.emitted('close')).toHaveLength(1)
})
