import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import EditorPreview from './EditorPreview.vue'
import { editorFixture } from './fixtures'

let callback: FrameRequestCallback | undefined
let paused: WeakMap<HTMLMediaElement, boolean>
beforeEach(() => {
  paused = new WeakMap()
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => { callback = cb; return 1 })
  vi.stubGlobal('cancelAnimationFrame', () => {})
  vi.spyOn(HTMLMediaElement.prototype, 'readyState', 'get').mockReturnValue(4)
  vi.spyOn(HTMLMediaElement.prototype, 'duration', 'get').mockReturnValue(2)
  vi.spyOn(HTMLMediaElement.prototype, 'paused', 'get').mockImplementation(function (this: HTMLMediaElement) { return paused.get(this) ?? true })
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {})
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(function (this: HTMLMediaElement) { paused.set(this, false); this.dispatchEvent(new Event('playing')); return Promise.resolve() })
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(function (this: HTMLMediaElement) { paused.set(this, true) })
})
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('syncs BGM position and fades to the video clock and silences it during buffering', async () => {
  const fixture = editorFixture()
  fixture.document.clips.push({ id: 'a', type: 'audio', name: 'BGM', start: 0, duration: 2, source: { kind: 'asset', id: 9 }, trim_in: 0, volume: .5, fade_in: 1, fade_out: 0, loop: false })
  fixture.media.push({ key: 'asset:9', source: { kind: 'asset', id: 9 }, kind: 'audio', name: 'BGM', duration: 2, url: '/music.wav' })
  const wrapper = mount(EditorPreview, { props: { document: fixture.document, media: fixture.media, time: 0, playing: false, muted: false, selectedId: 'v1' }, global: { stubs: { VideoThumbnail: true } } })
  await wrapper.setProps({ playing: true }); await flushPromises()
  await wrapper.setProps({ time: .5 }); callback?.(100); await flushPromises()
  const audio = wrapper.get('audio').element as HTMLAudioElement
  expect(audio.currentTime).toBeCloseTo(.5)
  expect(audio.volume).toBeCloseTo(.25)
  expect(paused.get(audio)).toBe(false)
  wrapper.get('video[src="/media/clip-1.mp4"]').element.dispatchEvent(new Event('waiting')); await flushPromises()
  expect(paused.get(audio)).toBe(true)
  await wrapper.setProps({ playing: false }); expect(paused.get(audio)).toBe(true)
  wrapper.unmount()
})

it('holds the last real video frame at the episode end instead of showing a new blank gap', () => {
  const fixture = editorFixture()
  const wrapper = mount(EditorPreview, { props: { document: fixture.document, media: fixture.media, time: 6, playing: false, muted: false, selectedId: 'v3' }, global: { stubs: { VideoThumbnail: true } } })
  expect(wrapper.find('.video-stage-blackout').exists()).toBe(false)
  wrapper.unmount()
})

it('presents standalone library audio as a preview rather than an empty timeline error', () => {
  const fixture = editorFixture()
  fixture.document.clips = [{ id: 'a', type: 'audio', name: 'Team music', start: 0, duration: 2, source: { kind: 'library', id: 9 }, trim_in: 0, volume: .5, fade_in: 0, fade_out: 0, loop: false }]
  fixture.media = [{ key: 'library:9', source: { kind: 'library', id: 9 }, kind: 'audio', name: 'Team music', duration: 2, url: '/music.wav' }]
  const wrapper = mount(EditorPreview, { props: { document: fixture.document, media: fixture.media, time: 0, playing: false, muted: false, selectedId: '' } })
  expect(wrapper.get('.editor-audio-preview').text()).toContain('Team music')
  expect(wrapper.text()).not.toContain('时间线空白')
  expect(wrapper.get('audio').attributes('src')).toBe('/music.wav')
  wrapper.unmount()
})

async function overlayPreview(kind:'subtitle'|'sticker',readOnly=false) {
  const fixture=editorFixture()
  fixture.document.clips.push(kind==='subtitle'
    ?{id:'overlay',type:'subtitle',name:'',start:0,duration:2,text:'拖拽字幕',font:'sans',font_size:42,color:'#ffffff',bottom:10}
    :{id:'overlay',type:'sticker',name:'',start:0,duration:2,source:{kind:'asset',id:9},x:50,y:50,scale:1,opacity:1})
  const wrapper=mount(EditorPreview,{props:{document:fixture.document,media:[],time:0,playing:false,muted:false,selectedId:'overlay',readOnly}})
  vi.spyOn(wrapper.get('.editor-preview-frame').element,'getBoundingClientRect').mockReturnValue({left:50,top:20,width:320,height:180} as DOMRect)
  vi.spyOn(wrapper.get('.editor-subtitle,.editor-sticker').element,'getBoundingClientRect').mockReturnValue({width:80,height:20} as DOMRect)
  return wrapper
}
function pointer(type:string,x:number,y:number) {return new MouseEvent(type,{clientX:x,clientY:y,button:0,bubbles:true,cancelable:true})}
it.each(['subtitle','sticker'] as const)('previews two-dimensional %s movement within the actual video frame and commits once',async kind=>{
  const wrapper=await overlayPreview(kind)
  const overlay=wrapper.get<HTMLButtonElement>('.editor-subtitle,.editor-sticker')
  overlay.element.dispatchEvent(pointer('pointerdown',100,100))
  window.dispatchEvent(pointer('pointermove',132,82));await flushPromises()
  expect(overlay.element.style.left).toBe('60%')
  expect(kind==='subtitle'?overlay.element.style.bottom:overlay.element.style.top).toBe(kind==='subtitle'?'20%':'40%')
  expect(wrapper.emitted('position')).toBeUndefined()
  expect(wrapper.props('document').clips.find(clip=>clip.id==='overlay')).not.toHaveProperty('x',60)
  window.dispatchEvent(pointer('pointerup',132,82));await flushPromises()
  expect(wrapper.emitted('position')).toEqual([['overlay',kind==='subtitle'?{x:60,bottom:20}:{x:60,y:40}]])
})
it.each(['subtitle','sticker'] as const)('keeps %s inside the frame and discards a cancelled drag',async kind=>{
  const wrapper=await overlayPreview(kind)
  const overlay=wrapper.get<HTMLButtonElement>('.editor-subtitle,.editor-sticker')
  overlay.element.dispatchEvent(pointer('pointerdown',100,100))
  window.dispatchEvent(pointer('pointermove',2000,2000));await flushPromises()
  expect(overlay.element.style.left).toBe('87.5%')
  expect(kind==='subtitle'?overlay.element.style.bottom:overlay.element.style.top).toBe(kind==='subtitle'?'0%':'94.44%')
  window.dispatchEvent(pointer('pointercancel',2000,2000));await flushPromises()
  expect(overlay.element.style.left).toBe('50%')
  expect(wrapper.emitted('position')).toBeUndefined()
})
it('allows viewers to select overlays but not reposition them',async()=>{
  const wrapper=await overlayPreview('subtitle',true)
  wrapper.get('.editor-subtitle').element.dispatchEvent(pointer('pointerdown',100,100))
  window.dispatchEvent(pointer('pointermove',132,82));window.dispatchEvent(pointer('pointerup',132,82));await flushPromises()
  expect(wrapper.emitted('position')).toBeUndefined()
  expect(wrapper.get<HTMLButtonElement>('.editor-subtitle').element.style.left).toBe('50%')
})

it('previews 20x clips with frame seeking when native media playback cannot reach that rate',async()=>{
  const fixture=editorFixture();fixture.document.clips=fixture.document.clips.slice(0,1)
  const clip=fixture.document.clips[0]!
  if(clip.type==='video')clip.speed=20
  const wrapper=mount(EditorPreview,{props:{document:fixture.document,media:fixture.media,time:0,playing:false,muted:false,selectedId:'v1'},global:{stubs:{VideoThumbnail:true}}})
  await wrapper.setProps({playing:true});await flushPromises()
  callback?.(100);callback?.(200);await flushPromises()
  expect(wrapper.emitted('update:time')?.at(-1)?.[0]).toBeCloseTo(.1)
  const video=wrapper.get('video[src="/media/clip-1.mp4"]').element as HTMLVideoElement
  expect(video.playbackRate).toBe(16)
  expect(video.currentTime).toBeCloseTo(2)
  wrapper.unmount()
})

it('rotates the fitted video viewport around its center for preview',()=>{
 const fixture=editorFixture();const clip=fixture.document.clips[0]!
 if(clip.type==='video'){clip.rotation=-5;clip.scale=1.2}
 const wrapper=mount(EditorPreview,{props:{document:fixture.document,media:fixture.media,time:0,playing:false,muted:false,selectedId:'v1'},global:{stubs:{VideoThumbnail:true}}})
 expect(wrapper.get<HTMLElement>('.editor-video-layer').element.style.transform).toBe('rotate(-5deg) scale(1.2)')
 wrapper.unmount()
})

it('shows sticker resize and rotation during dragging and commits only on release',async()=>{
 const wrapper=await overlayPreview('sticker')
 const sticker=wrapper.get<HTMLElement>('.editor-sticker')
 wrapper.get('.editor-sticker-resize').element.dispatchEvent(pointer('pointerdown',250,150))
 window.dispatchEvent(pointer('pointermove',290,150));await flushPromises()
 expect(sticker.element.style.width).toBe('37.5%')
 expect(wrapper.emitted('position')).toBeUndefined()
 window.dispatchEvent(pointer('pointerup',290,150));await flushPromises()
 expect(wrapper.emitted('position')?.at(-1)).toEqual(['overlay',{scale:1.5,scale_y:1.5}])
 wrapper.get('.editor-sticker-rotate').element.dispatchEvent(pointer('pointerdown',210,50))
 window.dispatchEvent(pointer('pointermove',270,110));await flushPromises()
 expect(sticker.element.style.transform).toBe('translate(-50%,-50%) rotate(90deg)')
 expect(wrapper.emitted('position')).toHaveLength(1)
 window.dispatchEvent(pointer('pointerup',270,110))
 expect(wrapper.emitted('position')?.at(-1)).toEqual(['overlay',{rotation:90}])
})
it('restores sticker transforms when cancelled and hides handles for viewers',async()=>{
 const wrapper=await overlayPreview('sticker')
 wrapper.get('.editor-sticker-rotate').element.dispatchEvent(pointer('pointerdown',210,50))
 window.dispatchEvent(pointer('pointermove',270,110));await flushPromises()
 window.dispatchEvent(pointer('pointercancel',270,110));await flushPromises()
 expect(wrapper.get<HTMLElement>('.editor-sticker').element.style.transform).toBe('translate(-50%,-50%) rotate(0deg)')
 expect(wrapper.emitted('position')).toBeUndefined()
 await wrapper.setProps({readOnly:true})
 expect(wrapper.find('.editor-sticker-handle').exists()).toBe(false)
})
it('keeps sticker controls visible at zero opacity and supports keyboard resizing and rotation',async()=>{
 const wrapper=await overlayPreview('sticker')
 const document={...wrapper.props('document'),clips:wrapper.props('document').clips.map(clip=>clip.id==='overlay'?{...clip,opacity:0}:clip)}
 await wrapper.setProps({document})
 expect(wrapper.get<HTMLElement>('.editor-sticker img').element.style.opacity).toBe('0')
 expect(wrapper.get<HTMLElement>('.editor-sticker').element.style.opacity).toBe('')
 await wrapper.get('.editor-sticker-resize').trigger('keydown',{key:'ArrowRight'})
 expect(wrapper.emitted('position')?.at(-1)).toEqual(['overlay',{scale:1.01,scale_y:1.01}])
 await wrapper.get('.editor-sticker-rotate').trigger('keydown',{key:'ArrowRight',shiftKey:true})
 expect(wrapper.emitted('position')?.at(-1)).toEqual(['overlay',{rotation:15}])
})

it('retries BGM without cross-origin processing and keeps the video playing', async () => {
  const fixture = editorFixture()
  fixture.document.clips.push({ id: 'a', type: 'audio', name: 'BGM', start: 0, duration: 2,
    source: { kind: 'asset', id: 9 }, trim_in: 0, volume: 2, fade_in: 0, fade_out: 0, loop: false })
  fixture.media.push({ key: 'asset:9', source: { kind: 'asset', id: 9 }, kind: 'audio', name: 'BGM',
    duration: 2, url: 'https://media.example.test/music.wav' })
  const wrapper = mount(EditorPreview, { props: { document: fixture.document, media: fixture.media, time: 0,
    playing: true, muted: false, selectedId: 'v1' }, global: { stubs: { VideoThumbnail: true } } })
  await flushPromises()
  const audio = wrapper.get<HTMLAudioElement>('audio')
  expect(audio.element.crossOrigin).toBe('anonymous')
  await audio.trigger('error')
  const fallback = wrapper.get<HTMLAudioElement>('audio')
  expect(fallback.element).not.toBe(audio.element)
  expect(fallback.element.crossOrigin).toBeNull()
  await fallback.trigger('loadedmetadata')
  expect(fallback.element.volume).toBe(1)
  expect(wrapper.emitted('update:playing')).toBeUndefined()
  expect(wrapper.find('[role="alert"]').exists()).toBe(false)
})

it('updates audio gain during playback without pausing or seeking the current video',async()=>{
  const fixture=editorFixture()
  fixture.document.clips.push({id:'a',type:'audio',name:'BGM',start:0,duration:2,source:{kind:'asset',id:9},trim_in:0,volume:.5,fade_in:0,fade_out:0,loop:false})
  fixture.media.push({key:'asset:9',source:{kind:'asset',id:9},kind:'audio',name:'BGM',duration:2,url:'/music.wav'})
  const wrapper=mount(EditorPreview,{props:{document:fixture.document,media:fixture.media,time:.5,playing:false,muted:false,selectedId:'v1'},global:{stubs:{VideoThumbnail:true}}})
  await wrapper.setProps({playing:true});await flushPromises()
  const video=wrapper.get('video[src="/media/clip-1.mp4"]').element as HTMLVideoElement
  video.currentTime=.6
  vi.mocked(HTMLMediaElement.prototype.pause).mockClear()
  const document={...fixture.document,clips:fixture.document.clips.map(clip=>clip.id==='a'?{...clip,volume:.2}:clip)}
  await wrapper.setProps({document});await flushPromises()
  callback?.(100);await flushPromises()
  expect(HTMLMediaElement.prototype.pause).not.toHaveBeenCalled()
  expect(video.currentTime).toBe(.6)
  expect(wrapper.get<HTMLAudioElement>('audio').element.volume).toBeCloseTo(.2)
  expect(wrapper.emitted('update:playing')?.some(([value])=>value===false)).toBeFalsy()
  wrapper.unmount()
})

it('previews a group move on all visible selected captions and commits once on release',async()=>{
  const wrapper=await overlayPreview('subtitle')
  const doc=wrapper.props('document'), original=doc.clips.find(c=>c.id==='overlay')!
  await wrapper.setProps({document:{...doc,clips:[...doc.clips,{...original,id:'second'},{...original,id:'unselected'}]},selectedIds:['overlay','second']})
  const captions=wrapper.findAll<HTMLButtonElement>('.editor-subtitle')
  captions[0]!.element.dispatchEvent(pointer('pointerdown',100,100))
  window.dispatchEvent(pointer('pointermove',132,82));await flushPromises()
  expect(captions.map(node=>node.element.style.left)).toEqual(['60%','60%','50%'])
  expect(wrapper.emitted('position')).toBeUndefined()
  window.dispatchEvent(pointer('pointerup',132,82));await flushPromises()
  expect(wrapper.emitted('position')).toEqual([['overlay',{x:60,bottom:20}]])
})

it.each(['light', 'dark'])('updates the paused preview when the selected font finishes loading (%s)', async theme => {
  const font = `live-${theme}`
  document.documentElement.dataset.appTheme = theme
  let resolve!: (response: Response) => void
  const fetchFont = vi.fn(() => new Promise<Response>(done => { resolve = done }))
  vi.stubGlobal('fetch', fetchFont)
  vi.stubGlobal('FontFace', class { async load() { return this } })
  const fontSet = { add: vi.fn() }
  const priorFonts = Object.getOwnPropertyDescriptor(document, 'fonts')
  Object.defineProperty(document, 'fonts', { configurable: true, value: fontSet })
  const wrapper = await overlayPreview('subtitle')
  try {
    const current = wrapper.props('document')
    await wrapper.setProps({
      document: { ...current, clips: current.clips.map(clip => clip.type === 'subtitle' ? { ...clip, font } : clip) },
    })
    const subtitle = wrapper.get<HTMLButtonElement>('.editor-subtitle')
    expect(wrapper.get('[role="status"]').text()).toBe('正在加载字幕字体…')
    expect(subtitle.element.style.fontFamily).not.toContain(font)
    resolve(new Response(new Uint8Array([0]), { headers: { 'Content-Type': 'font/ttf' } }))
    await flushPromises()
    expect(fontSet.add).toHaveBeenCalledOnce()
    expect(subtitle.element.style.fontFamily).toContain(`Subtitle-${font}`)
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    expect(wrapper.emitted('update:playing')).toBeUndefined()
  } finally {
    wrapper.unmount()
    if (priorFonts) Object.defineProperty(document, 'fonts', priorFonts)
    else Reflect.deleteProperty(document, 'fonts')
    delete document.documentElement.dataset.appTheme
  }
})
