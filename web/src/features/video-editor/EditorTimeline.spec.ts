import { mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import EditorTimeline from './EditorTimeline.vue'
import { editorFixture } from './fixtures'

function render(readOnly = false) {
  const fixture = editorFixture()
  const wrapper = mount(EditorTimeline, { props: { document: fixture.document, media: [], time: 2, selectedId: 'v1', readOnly, canUndo: false, canRedo: false } })
  const viewport = wrapper.get('.editor-timeline-scroll').element
  vi.spyOn(viewport, 'getBoundingClientRect').mockReturnValue({ left: 100 } as DOMRect)
  viewport.scrollLeft = 24
  return wrapper
}
function pointer(type: string, clientX: number, button = 0) {
  return new MouseEvent(type, { clientX, button, bubbles: true, cancelable: true })
}
it.each(['dark', 'light'])('drags the playhead across tracks, accounting for scroll and zoom (%s)', async theme => {
  document.documentElement.dataset.appTheme = theme
  const wrapper = render()
  await wrapper.get('input[type=range]').setValue(24)
  wrapper.get('.editor-playhead').element.dispatchEvent(pointer('pointerdown', 124))
  expect(wrapper.emitted('seek')?.at(-1)).toEqual([2])
  window.dispatchEvent(pointer('pointermove', 172))
  expect(wrapper.emitted('seek')?.at(-1)).toEqual([4])
  window.dispatchEvent(pointer('pointermove', -100))
  expect(wrapper.emitted('seek')?.at(-1)).toEqual([0])
  window.dispatchEvent(pointer('pointerup', 1000))
  expect(wrapper.emitted('seek')?.at(-1)).toEqual([6])
  const count = wrapper.emitted('seek')!.length
  window.dispatchEvent(pointer('pointermove', 124))
  expect(wrapper.emitted('seek')).toHaveLength(count)
  expect(wrapper.emitted('move')).toBeUndefined()
  expect(wrapper.emitted('edge')).toBeUndefined()
})
it('allows ruler scrubbing in read-only mode and releases listeners on cancellation and unmount', () => {
  const wrapper = render(true)
  wrapper.get('.editor-time-ruler').element.dispatchEvent(pointer('pointerdown', 100))
  expect(wrapper.emitted('seek')?.at(-1)).toEqual([3]) // fit clamps the empty viewport to 8px per second
  window.dispatchEvent(pointer('pointercancel', 100))
  const count = wrapper.emitted('seek')!.length
  window.dispatchEvent(pointer('pointermove', 110))
  expect(wrapper.emitted('seek')).toHaveLength(count)
  wrapper.get('.editor-playhead').element.dispatchEvent(pointer('pointerdown', 100))
  const remove = vi.spyOn(window, 'removeEventListener')
  wrapper.unmount()
  window.dispatchEvent(pointer('pointermove', 110))
  for (const type of ['pointermove', 'pointerup', 'pointercancel']) expect(remove).toHaveBeenCalledWith(type, expect.any(Function))
})
it('ignores secondary mouse buttons', () => {
  const wrapper = render()
  wrapper.get('.editor-playhead').element.dispatchEvent(pointer('pointerdown', 120, 2))
  window.dispatchEvent(pointer('pointermove', 150))
  expect(wrapper.emitted('seek')).toBeUndefined()
})
