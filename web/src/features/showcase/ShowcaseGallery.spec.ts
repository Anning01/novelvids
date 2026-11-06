import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import ShowcaseGallery from './ShowcaseGallery.vue'
import type { ShowcaseWork } from '@/types'

const works: ShowcaseWork[] = [
  {id:'one',title:'雨夜来信',cover:'/media/one.webp',video_url:'/api/portfolio/public/1/episodes/11/video',episodes_count:2,duration:'01:12',category:'悬疑',tags:[],heat:'',description:'一封来自过去的信。',author:'创作者甲',novel_id:1,cover_width:1920,cover_height:1080},
  {id:'two',title:'山间来客',cover:'/media/two.webp',video_url:'/api/portfolio/public/2/episodes/22/video',episodes_count:1,duration:'00:48',category:'古风',tags:[],heat:'',description:'山间的一场相遇。',author:'创作者乙',novel_id:2,cover_width:1080,cover_height:1920},
]
const nativeShowModal = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'showModal')
const nativeClose = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'close')
let wrapper: ReturnType<typeof mount> | undefined
beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value:vi.fn(function(this:HTMLDialogElement) {this.setAttribute('open','')})})
  Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value:vi.fn(function(this:HTMLDialogElement) {if(this.open){this.removeAttribute('open');this.dispatchEvent(new Event('close'))}})})
  vi.spyOn(HTMLMediaElement.prototype,'pause').mockImplementation(()=>{})
})
afterEach(() => {
  wrapper?.unmount();wrapper=undefined;vi.restoreAllMocks();document.body.style.overflow=''
  for (const [name, descriptor] of [['showModal',nativeShowModal],['close',nativeClose]] as const) {
    if (descriptor) Object.defineProperty(HTMLDialogElement.prototype,name,descriptor)
    else Reflect.deleteProperty(HTMLDialogElement.prototype,name)
  }
})
function render(items=works) {
  wrapper=mount(ShowcaseGallery,{props:{works:items,loading:false},attachTo:document.body,global:{stubs:{Teleport:true,RouterLink:{props:['to'],template:'<a :href="to"><slot/></a>'}}}})
  return wrapper
}
it('uses native cover proportions and keeps even a single work in the masonry list',()=>{
  const view=render()
  expect(view.findAll('.showcase-card')).toHaveLength(2)
  expect(view.findAll('.work-visual')[0]!.attributes('style')).toContain('1920')
  expect(view.findAll('.work-visual')[1]!.attributes('style')).toContain('1080')
  expect(view.find('.is-single').exists()).toBe(false)
  expect(view.get('.showcase-card').element.tagName).toBe('BUTTON')
})
it('opens the selected video beside its introduction without navigating away',async()=>{
  const view=render()
  await view.findAll('.showcase-card')[1]!.trigger('click');await flushPromises()
  expect(view.get('dialog').attributes('open')).toBeDefined()
  expect(view.get('video').attributes('src')).toBe(works[1]!.video_url)
  expect(view.get('#showcase-viewer-title').text()).toBe('山间来客')
  expect(view.get('.viewer-introduction').text()).toContain('山间的一场相遇。')
  expect(view.get('.viewer-author').text()).toBe('创作者乙')
  expect(document.body.style.overflow).toBe('hidden')
  expect(document.activeElement).toBe(view.get('[aria-label="关闭播放器"]').element)
})
it('switches videos, pauses the previous video, and bounds previous/next navigation',async()=>{
  const view=render()
  await view.findAll('.showcase-card')[0]!.trigger('click');await flushPromises()
  expect(view.get('[aria-label="上一个作品"]').attributes('disabled')).toBeDefined()
  await view.get('[aria-label="下一个作品"]').trigger('click');await flushPromises()
  expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled()
  expect(view.get('video').attributes('src')).toBe(works[1]!.video_url)
  expect(view.get('[aria-label="下一个作品"]').attributes('disabled')).toBeDefined()
  await view.get('dialog').trigger('keydown',{key:'ArrowLeft'});await flushPromises()
  expect(view.get('video').attributes('src')).toBe(works[0]!.video_url)
  await view.get('video').trigger('keydown',{key:'ArrowRight'});await flushPromises()
  expect(view.get('video').attributes('src')).toBe(works[0]!.video_url)
})
it('closes with Escape, stops playback and restores scroll and keyboard focus',async()=>{
  const view=render()
  const card=view.findAll('.showcase-card')[0]!
  ;(card.element as HTMLButtonElement).focus()
  document.body.style.overflow='auto'
  await card.trigger('click');await flushPromises()
  await view.get('dialog').trigger('cancel');await flushPromises()
  expect(view.get('dialog').attributes('open')).toBeUndefined()
  expect(view.find('video').exists()).toBe(false)
  expect(document.body.style.overflow).toBe('auto')
  expect(document.activeElement).toBe(card.element)
  expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled()
})
it('shows loading and retryable playback failure without a fake playable result',async()=>{
  const view=render([works[0]!])
  await view.get('.showcase-card').trigger('click');await flushPromises()
  expect(view.get('.viewer-loading').text()).toContain('正在加载视频')
  expect(view.find('[aria-label="下一个作品"]').exists()).toBe(false)
  await view.get('video').trigger('canplay')
  expect(view.find('.viewer-loading').exists()).toBe(false)
  await view.get('video').trigger('error');await flushPromises()
  expect(view.get('.viewer-unavailable').text()).toContain('无法播放')
  expect(view.find('video').exists()).toBe(false)
  await view.get('.viewer-unavailable button').trigger('click');await flushPromises()
  expect(view.get('video').attributes('src')).toBe(works[0]!.video_url)
})
it('closes removed works and restores page scrolling on unmount',async()=>{
  const view=render()
  await view.get('.showcase-card').trigger('click');await flushPromises()
  await view.setProps({works:[]});await flushPromises()
  expect(view.get('dialog').attributes('open')).toBeUndefined()
  expect(document.body.style.overflow).toBe('')
  expect(view.text()).toContain('还没有公开作品')
})
it('handles unavailable covers and does not expose internal project metadata as a description',async()=>{
  const view=render([{...works[0]!,description:'Agent 模式 · 源剧本：internal.txt',video_url:''}])
  await view.get('.work-visual img').trigger('error')
  expect(view.get('.cover-fallback').text()).toContain('封面暂不可用')
  await view.get('.showcase-card').trigger('click');await flushPromises()
  expect(view.get('.viewer-unavailable').text()).toContain('暂无可播放')
  expect(view.get('.viewer-introduction').text()).toContain('暂无作品介绍')
  expect(view.text()).not.toContain('internal.txt')
})
