import { mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import EditorTimeline from './EditorTimeline.vue'
import { editorFixture } from './fixtures'
import type { AudioClip } from './types'

function render(readOnly = false) {
  const fixture = editorFixture()
  const wrapper = mount(EditorTimeline, { props: { document: fixture.document, media: [], time: 2, selectedId: 'v1', readOnly, canUndo: false, canRedo: false } })
  const viewport = wrapper.get('.editor-timeline-scroll').element
  vi.spyOn(wrapper.get('.editor-tracks-canvas').element, 'getBoundingClientRect').mockImplementation(() => ({ left: 100 - viewport.scrollLeft } as DOMRect))
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

async function subtitleTimeline() {
  const wrapper=render()
  const document=editorFixture().document
  document.clips.push({id:'sub',type:'subtitle',name:'Caption',start:2,duration:6.7,text:'字幕',font:'sans',font_size:42,color:'#ffffff',bottom:10})
  await wrapper.setProps({document,selectedId:'sub'})
  await wrapper.get('input[type=range]').setValue(24)
  return wrapper
}
it.each(['dark','light'])('shows subtitle movement during pointer movement before committing once on release (%s)',async theme=>{
  document.documentElement.dataset.appTheme=theme
  const wrapper=await subtitleTimeline()
  const clip=wrapper.get<HTMLButtonElement>('.clip-subtitle')
  clip.element.dispatchEvent(pointer('pointerdown',100))
  window.dispatchEvent(pointer('pointermove',124));await wrapper.vm.$nextTick()
  expect(clip.element.style.transform).toBe('translateX(24px)')
  expect(clip.classes()).toContain('is-dragging')
  expect(wrapper.props('document').clips.find(clip=>clip.id==='sub')?.start).toBe(2)
  expect(wrapper.emitted('move')).toBeUndefined()
  window.dispatchEvent(pointer('pointerup',148));await wrapper.vm.$nextTick()
  expect(wrapper.emitted('move')).toEqual([['sub',4]])
  expect(clip.classes()).not.toContain('is-dragging')
})
it.each(['left','right'])('previews subtitle %s edge position, width and duration before committing',async side=>{
  const wrapper=await subtitleTimeline()
  const clip=wrapper.get<HTMLButtonElement>('.clip-subtitle')
  wrapper.get(`.clip-subtitle .editor-clip-handle.${side}`).element.dispatchEvent(pointer('pointerdown',100))
  window.dispatchEvent(pointer('pointermove',124));await wrapper.vm.$nextTick()
  expect(Number.parseFloat(clip.element.style.width)).toBeCloseTo(side==='left'?135:183)
  expect(clip.get('small').text()).toBe(side==='left'?'5.7s':'7.7s')
  expect(wrapper.props('document').clips.find(clip=>clip.id==='sub')?.duration).toBe(6.7)
  expect(wrapper.emitted('edge')).toBeUndefined()
  window.dispatchEvent(pointer('pointerup',124))
  expect(wrapper.emitted('edge')).toEqual([['sub',side,1]])
})
it('accounts for timeline scrolling during a drag and cancels without a document change',async()=>{
  const wrapper=await subtitleTimeline()
  wrapper.get<HTMLButtonElement>('.clip-subtitle').element.dispatchEvent(pointer('pointerdown',100))
  wrapper.get('.editor-timeline-scroll').element.scrollLeft+=24
  window.dispatchEvent(pointer('pointermove',124));await wrapper.vm.$nextTick()
  expect(wrapper.get<HTMLButtonElement>('.clip-subtitle').element.style.transform).toBe('translateX(48px)')
  window.dispatchEvent(pointer('pointercancel',124));await wrapper.vm.$nextTick()
  expect(wrapper.get<HTMLButtonElement>('.clip-subtitle').element.style.transform).toBe('')
  expect(wrapper.emitted('move')).toBeUndefined()
  window.dispatchEvent(pointer('pointerup',124))
  expect(wrapper.emitted('move')).toBeUndefined()
})

it.each(['light', 'dark'])('shows overlapping BGM on separate selectable rows in the shared scroll area (%s)', async theme => {
  document.documentElement.dataset.appTheme = theme
  const wrapper = render()
  const documentValue = editorFixture().document
  const music: AudioClip = { id: 'music', type: 'audio', name: 'Music', start: 0, duration: 4,
    source: { kind: 'asset', id: 9 }, trim_in: 0, volume: 1, fade_in: 0, fade_out: 0, loop: false }
  documentValue.clips.push(music, { ...music, id: 'second', name: 'Second', start: 1 },
    { ...music, id: 'continued', name: 'Continued', start: 4 })
  const scroll = wrapper.get<HTMLElement>('.editor-timeline-scroll')
  Object.defineProperties(scroll.element, { clientWidth: { value: 300 }, clientHeight: { value: 160 } })
  vi.spyOn(scroll.element, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 100 } as DOMRect)
  await wrapper.setProps({ document: documentValue })
  expect(scroll.findAll('.editor-track-name strong').map(label => label.text())).toEqual(['贴纸', '字幕', '视频', 'BGM 1', 'BGM 2'])
  const [first, second, continued] = scroll.findAll<HTMLButtonElement>('.clip-audio')
  expect(first?.element.style.top).toBe('4px')
  expect(second?.element.style.top).toBe('52px')
  expect(continued?.element.style.top).toBe('4px')
  vi.spyOn(second!.element, 'getBoundingClientRect').mockReturnValue({ left: 125, right: 220, top: 280, bottom: 324, width: 95, height: 44 } as DOMRect)
  await second!.trigger('click')
  expect(wrapper.emitted('select')).toEqual([['second']])
  await wrapper.setProps({ selectedId: 'second' })
  expect(scroll.element.scrollTop).toBe(64)
})

it('snaps BGM edges during the drag and shows another row only for intentional overlap', async () => {
  const wrapper = render()
  const documentValue = editorFixture().document
  const audio: AudioClip = { id: 'first', type: 'audio', name: 'First', start: 0, duration: 4,
    source: { kind: 'asset', id: 1 }, trim_in: 0, volume: 1, fade_in: 0, fade_out: 0, loop: false }
  documentValue.clips.push(audio, { ...audio, id: 'second', name: 'Second', start: 5 })
  await wrapper.setProps({ document: documentValue, selectedId: 'second' })
  await wrapper.get('input[type=range]').setValue(24)
  const second = wrapper.get<HTMLButtonElement>('[aria-label="选择BGM：Second"]')
  second.element.dispatchEvent(pointer('pointerdown', 200))
  window.dispatchEvent(pointer('pointermove', 172)); await wrapper.vm.$nextTick()
  expect(second.element.style.transform).toBe('translateX(-24px)')
  expect(wrapper.text()).not.toContain('BGM 2')
  window.dispatchEvent(pointer('pointermove', 160)); await wrapper.vm.$nextTick()
  expect(second.element.style.top).toBe('52px')
  expect(wrapper.text()).toContain('BGM 2')
  window.dispatchEvent(pointer('pointermove', 180)); await wrapper.vm.$nextTick()
  expect(second.element.style.top).toBe('4px')
  window.dispatchEvent(pointer('pointerup', 180))
  expect(wrapper.emitted('move')).toEqual([['second', 4]])
})
