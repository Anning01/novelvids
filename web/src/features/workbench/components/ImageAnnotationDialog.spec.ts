import { mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import ImageAnnotationDialog from './ImageAnnotationDialog.vue'

it('offers the six reference tools and keeps save explicit', async () => {
  const wrapper = mount(ImageAnnotationDialog, {
    attachTo: document.body,
    props: {
      open: true,
      imageUrl: '/media/photo.png',
      modelValue: [],
    },
    global: { stubs: { Teleport: true } },
  })
  expect(wrapper.get('[aria-label="批注工具"]').findAll('button').map(button => button.attributes('aria-label')))
    .toEqual(['移动', '矩形', '椭圆', '网格', '箭头', '涂鸦'])
  await wrapper.get('[aria-label="清空批注"]').trigger('click')
  await wrapper.get('[aria-label="撤销批注操作"]').trigger('click')
  expect(wrapper.emitted('save')).toBeUndefined()
  wrapper.unmount()
})

it('keeps cancel and save separate and enables save only after a drawing change', async () => {
  const wrapper = mount(ImageAnnotationDialog, {
    props: {
      open: true,
      imageUrl: '/media/photo.png',
      modelValue: [],
    },
    global: { stubs: { Teleport: true } },
  })

  await wrapper.get('[aria-label="取消图片标注"]').trigger('click')
  expect(wrapper.emitted('close')).toHaveLength(1)
  expect(wrapper.emitted('save')).toBeUndefined()

  expect(wrapper.get('[aria-label="保存图片标注"]').attributes('disabled')).toBeDefined()
  await wrapper.get('[aria-label="矩形"]').trigger('click')
  const canvas = wrapper.get('[aria-label="图片批注画布"]')
  vi.spyOn(canvas.element, 'getBoundingClientRect').mockReturnValue({
    x: 0, y: 0, left: 0, top: 0, right: 100, bottom: 100, width: 100, height: 100, toJSON: () => ({}),
  })
  const pointerDown = new MouseEvent('pointerdown', { bubbles: true, clientX: 10, clientY: 10 })
  const pointerUp = new MouseEvent('pointerup', { bubbles: true, clientX: 50, clientY: 50 })
  Object.defineProperty(pointerDown, 'pointerId', { value: 1 })
  Object.defineProperty(pointerUp, 'pointerId', { value: 1 })
  canvas.element.dispatchEvent(pointerDown)
  canvas.element.dispatchEvent(pointerUp)
  await wrapper.vm.$nextTick()
  expect(wrapper.get('[aria-label="保存图片标注"]').attributes('disabled')).toBeUndefined()
  await wrapper.get('[aria-label="保存图片标注"]').trigger('click')
  expect(wrapper.emitted('save')?.[0]?.[0]).toMatchObject([
    { tool: 'rectangle', points: [{ x: 0.1, y: 0.1 }, { x: 0.5, y: 0.5 }] },
  ])
})
