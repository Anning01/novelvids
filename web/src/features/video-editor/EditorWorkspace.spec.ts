import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { editorApi } from './api'
import { editorFixture } from './fixtures'
import type { AudioClip, EditDocument } from './types'
import EditorWorkspace from './EditorWorkspace.vue'
import EditorLibrary from './EditorLibrary.vue'
import EditorTimeline from './EditorTimeline.vue'
import EditorPreview from './EditorPreview.vue'
import AppSelect from '@/components/AppSelect.vue'
import EditorInspector from './EditorInspector.vue'
import { useAuthStore } from '@/features/auth/authStore'

vi.mock('./api', () => ({ editorApi: { get: vi.fn(), save: vi.fn(), capabilities: vi.fn(), history: vi.fn(), export: vi.fn(), upload: vi.fn(), cancel: vi.fn(), recognizeSubtitles: vi.fn(), splitSubtitles: vi.fn() } }))
beforeEach(() => {
  vi.clearAllMocks(); sessionStorage.clear()
  vi.mocked(editorApi.get).mockResolvedValue({ data: editorFixture() } as never)
  vi.mocked(editorApi.capabilities).mockResolvedValue({ data: { formats: { video: ['mp4'], audio: ['mp3'], sticker: ['png'] }, max_size_mb: 200, fps: [24, 30], resolutions: [480, 720, 1080] } } as never)
  vi.mocked(editorApi.history).mockResolvedValue({ data: [] } as never)
  vi.mocked(editorApi.save).mockImplementation(async (_id, revision, document) => ({ data: { revision: revision + 1, document, updated_at: '' } }) as never)
})
function render(readOnly = false, attachTo?: HTMLElement) {
  const pinia = createPinia(); const auth = useAuthStore(pinia)
  if (readOnly) { auth.enabled = true; auth.memberships = [{ team_id: 1, role: 'viewer' }] as never }
  return mount(EditorWorkspace, { attachTo, props: { projectId: 9, chapterId: 450, filename: 'episode' }, global: { plugins: [pinia], stubs: { ResourceLibraryPicker: true, EditorPreview: { template: '<div></div>', methods: { seek() {} }, expose: ['seek'] } } } })
}
it.each(['dark', 'light'])('connects library, inspector and timeline while preserving source media (%s)', async theme => {
  document.documentElement.dataset.appTheme = theme
  const wrapper = render(); await flushPromises()
  expect(wrapper.findComponent(EditorLibrary).exists()).toBe(true)
  expect(wrapper.findComponent(EditorInspector).props('clip')).toMatchObject({ id: 'v1' })
  wrapper.findComponent(EditorTimeline).vm.$emit('select', 'v2'); await flushPromises()
  expect(wrapper.findComponent(EditorInspector).props('clip')).toMatchObject({ id: 'v2' })
  wrapper.findComponent(EditorTimeline).vm.$emit('remove'); await flushPromises()
  expect(wrapper.findComponent(EditorTimeline).props('document').clips.map(clip => [clip.id, clip.start])).toEqual([['v1', 0], ['v3', 2]])
  expect(wrapper.findComponent(EditorLibrary).props('media')).toHaveLength(3)
  wrapper.findComponent(EditorTimeline).vm.$emit('undo'); await flushPromises()
  expect(wrapper.findComponent(EditorTimeline).props('document').clips).toHaveLength(3)
  wrapper.unmount()
})
it('flushes the exact edited revision before starting a render and restores persisted export history', async () => {
  vi.mocked(editorApi.export).mockResolvedValue({ data: { id: 4, task_id: 'task', status: 6, progress: 0, revision: 2 } } as never)
  const wrapper = render(); await flushPromises()
  wrapper.findComponent(EditorLibrary).vm.$emit('subtitle'); await flushPromises()
  wrapper.vm.openExport(); await flushPromises()
  await document.querySelector<HTMLButtonElement>('.editor-export-dialog .primary')?.click(); await flushPromises()
  expect(editorApi.save).toHaveBeenCalled()
  expect(editorApi.export).toHaveBeenCalledWith(450, 2)
  const doc = vi.mocked(editorApi.save).mock.calls[0]?.[2]
  expect(doc?.clips.some(c => c.type === 'subtitle')).toBe(true)
  wrapper.unmount()
})
it('does not expose edit or export permissions to viewers', async () => {
  const wrapper = render(true); await flushPromises()
  expect(wrapper.findComponent(EditorLibrary).props('readOnly')).toBe(true)
  expect(wrapper.findComponent(EditorTimeline).props('readOnly')).toBe(true)
  wrapper.findComponent(EditorLibrary).vm.$emit('subtitle'); await flushPromises()
  expect(wrapper.findComponent(EditorTimeline).props('document').clips).toHaveLength(3)
  wrapper.vm.openExport(); await flushPromises()
  expect(document.querySelector<HTMLButtonElement>('.editor-export-dialog .primary')?.disabled).toBe(true)
  wrapper.unmount()
})

it('browses an imported source without inserting it until explicitly added', async () => {
  const wrapper = render(); await flushPromises()
  const source = { key: 'asset:9', source: { kind: 'asset' as const, id: 9 }, kind: 'video' as const, name: 'Extra', url: '/extra.mp4', duration: 2 }
  wrapper.findComponent(EditorLibrary).vm.$emit('select', source); await flushPromises()
  expect(wrapper.findComponent(EditorTimeline).props('document').clips).toHaveLength(3)
  expect(wrapper.findComponent(EditorInspector).props('clip')).toBeNull()
  wrapper.findComponent(EditorLibrary).vm.$emit('add', source); await flushPromises()
  expect(wrapper.findComponent(EditorTimeline).props('document').clips).toHaveLength(4)
  wrapper.unmount()
})

it('pins the media category for an upload batch while other add controls are used', async () => {
  const item = { key: 'asset:9', source: { kind: 'asset' as const, id: 9 }, kind: 'audio' as const, name: 'Music', url: '/music.wav', duration: 2 }
  let resolve!: (value: typeof item) => void
  vi.mocked(editorApi.upload).mockImplementationOnce(() => new Promise(r => { resolve = r })).mockResolvedValue(item)
  const wrapper = render(); await flushPromises()
  wrapper.findComponent(EditorLibrary).vm.$emit('upload', 'audio'); await flushPromises()
  const element = wrapper.findAll('input[type="file"]')[0]!
  Object.defineProperty(element.element, 'files', { configurable: true, value: [new File(['x'], 'a.mp3'), new File(['x'], 'b.mp3')] })
  await element.trigger('change'); await flushPromises()
  expect(wrapper.findComponent(EditorLibrary).props('busy')).toBe(true)
  wrapper.findComponent(EditorLibrary).vm.$emit('upload', 'sticker'); await flushPromises()
  resolve(item); await flushPromises()
  expect(vi.mocked(editorApi.upload).mock.calls.map(call => call[2])).toEqual(['audio', 'audio'])
  expect(wrapper.findComponent(EditorTimeline).props('document').clips).toHaveLength(3)
  wrapper.unmount()
})

it.each([
  ['dark', 'metaKey'],
  ['light', 'ctrlKey'],
] as const)('undoes and redoes keyboard edits while timeline controls retain focus (%s, %s)', async (theme, modifier) => {
  document.documentElement.dataset.appTheme = theme
  const wrapper = render(false, document.body); await flushPromises()
  try {
    const clip = wrapper.findAll('.editor-track-clip').at(-1)!
    await clip.trigger('click')
    await clip.trigger('keydown', { key: 'ArrowLeft' })
    expect(wrapper.findComponent(EditorTimeline).props('document').clips[2].start).toBe(2)
    const undo = wrapper.get('button[aria-label="撤销"]')
    expect(undo.attributes('disabled')).toBeUndefined()
    await undo.trigger('click')
    expect(wrapper.findComponent(EditorTimeline).props('document').clips[2].start).toBe(4)
    await wrapper.get('button[aria-label="重做"]').trigger('click')
    expect(wrapper.findComponent(EditorTimeline).props('document').clips[2].start).toBe(2)

    for (const selector of ['.editor-track-clip.selected', '.editor-clip-handle.left', 'button[aria-label="撤销"]']) {
      await wrapper.get(selector).trigger('keydown', { key: 'z', [modifier]: true })
      expect(wrapper.findComponent(EditorTimeline).props('document').clips[2].start).toBe(4)
      await wrapper.get('.editor-track-clip.selected').trigger('keydown', { key: 'z', [modifier]: true, shiftKey: true })
      expect(wrapper.findComponent(EditorTimeline).props('document').clips[2].start).toBe(2)
    }
    const input = wrapper.get('.editor-search input')
    const event = new KeyboardEvent('keydown', { key: 'z', [modifier]: true, bubbles: true, cancelable: true })
    input.element.dispatchEvent(event); await flushPromises()
    expect(event.defaultPrevented).toBe(false)
    expect(wrapper.findComponent(EditorTimeline).props('document').clips[2].start).toBe(2)
  } finally { wrapper.unmount() }
})

it('keeps timeline undo shortcuts inactive for read-only viewers', async () => {
  const wrapper = render(true, document.body); await flushPromises()
  try {
    const event = new KeyboardEvent('keydown', { key: 'z', metaKey: true, bubbles: true, cancelable: true })
    wrapper.get('.editor-track-clip').element.dispatchEvent(event); await flushPromises()
    expect(event.defaultPrevented).toBe(false)
    expect(wrapper.findComponent(EditorTimeline).props('document')).toEqual(editorFixture().document)
    expect(wrapper.get('button[aria-label="撤销"]').attributes('disabled')).toBeDefined()
  } finally { wrapper.unmount() }
})

it('updates the preview when the timeline playhead seeks', async () => {
  const wrapper = render(); await flushPromises()
  const preview = wrapper.findComponent(EditorPreview)
  const seek = vi.spyOn(preview.vm, 'seek')
  wrapper.findComponent(EditorTimeline).vm.$emit('seek', 3.5); await flushPromises()
  expect(wrapper.findComponent(EditorTimeline).props('time')).toBe(3.5)
  expect(seek).toHaveBeenCalledOnce()
  wrapper.unmount()
})

function musicFixture() {
  const fixture=editorFixture()
  const music:AudioClip={id:'music',type:'audio',name:'月影.mp3',start:0,duration:4,trim_in:1,source:{kind:'asset',id:9},volume:.6,fade_in:.5,fade_out:1,loop:false}
  fixture.document.clips.push(music)
  fixture.media.push({key:'asset:9',source:music.source,kind:'audio',name:music.name,url:'/music.mp3',duration:5})
  vi.mocked(editorApi.get).mockResolvedValue({data:fixture} as never)
  return music
}
it.each(['metaKey','ctrlKey'] as const)('copies a snapshot and appends music despite the playhead being inside the source, with undo and redo (%s)',async modifier=>{
  const music=musicFixture()
  const wrapper=render(false,document.body);await flushPromises()
  try {
    await wrapper.get('.clip-audio').trigger('click')
    await wrapper.get('.clip-audio').trigger('keydown',{key:'c',[modifier]:true})
    wrapper.findComponent(EditorInspector).vm.$emit('change',{volume:.2});await flushPromises()
    wrapper.findComponent(EditorTimeline).vm.$emit('seek',1);await flushPromises()
    await wrapper.get('.clip-audio').trigger('keydown',{key:'v',[modifier]:true})
    const timeline=wrapper.findComponent(EditorTimeline)
    let clips=timeline.props('document').clips.filter(clip=>clip.type==='audio')
    expect(clips).toHaveLength(2)
    expect(clips[1]).toEqual({...music,id:expect.any(String),start:4})
    expect(clips[0].volume).toBe(.2)
    expect(timeline.props('time')).toBe(8)
    expect(wrapper.findAll<HTMLButtonElement>('.clip-audio').map(clip => clip.element.style.top)).toEqual(['4px', '4px'])
    await wrapper.get('.clip-audio.selected').trigger('keydown',{key:'v',[modifier]:true})
    clips=timeline.props('document').clips.filter(clip=>clip.type==='audio')
    expect(clips.map(clip=>clip.start)).toEqual([0,4,8])
    expect(new Set(clips.map(clip=>clip.id)).size).toBe(3)
    await wrapper.get('.clip-audio.selected').trigger('keydown',{key:'z',[modifier]:true})
    expect(timeline.props('document').clips).toHaveLength(5)
    await wrapper.get('.editor-workspace').trigger('keydown',{key:'z',[modifier]:true,shiftKey:true})
    expect(timeline.props('document').clips).toHaveLength(6)
  } finally {wrapper.unmount()}
})
it.each(['metaKey','ctrlKey'] as const)('duplicates selected music end to end using the shortcut (%s)',async modifier=>{
  musicFixture()
  const wrapper=render(false,document.body);await flushPromises()
  try {
    await wrapper.get('.clip-audio').trigger('click')
    for(let i=0;i<2;i++)await wrapper.get('.clip-audio.selected').trigger('keydown',{key:'d',[modifier]:true})
    const clips=wrapper.findComponent(EditorTimeline).props('document').clips.filter(clip=>clip.type==='audio')
    expect(clips.map(clip=>clip.start)).toEqual([0,4,8])
  } finally {wrapper.unmount()}
})
it('preserves native text clipboard shortcuts and clears copied clips when chapters change',async()=>{
  musicFixture()
  const wrapper=render(false,document.body);await flushPromises()
  try {
    await wrapper.get('.clip-audio').trigger('click')
    await wrapper.get('.clip-audio').trigger('keydown',{key:'c',metaKey:true})
    for(const key of ['c','v','d']){
      const event=new KeyboardEvent('keydown',{key,metaKey:true,bubbles:true,cancelable:true})
      wrapper.get('.editor-search input').element.dispatchEvent(event)
      expect(event.defaultPrevented).toBe(false)
    }
    await wrapper.setProps({chapterId:451});await flushPromises()
    const event=new KeyboardEvent('keydown',{key:'v',metaKey:true,bubbles:true,cancelable:true})
    wrapper.get('.editor-workspace').element.dispatchEvent(event);await flushPromises()
    expect(event.defaultPrevented).toBe(false)
    expect(wrapper.findComponent(EditorTimeline).props('document').clips).toHaveLength(4)
  } finally {wrapper.unmount()}
})
it('does not paste or duplicate clips for viewers',async()=>{
  musicFixture()
  const wrapper=render(true,document.body);await flushPromises()
  try {
    for(const key of ['c','v','d'])await wrapper.get('.clip-audio').trigger('keydown',{key,metaKey:true})
    expect(wrapper.findComponent(EditorTimeline).props('document').clips).toHaveLength(4)
  } finally {wrapper.unmount()}
})

it.each([
  ['light','Delete'],['dark','Delete'],['light','Backspace'],['dark','Backspace'],
])('removes the selected music from focused clips and trim handles and supports undo (%s, %s)',async(theme,key)=>{
  document.documentElement.dataset.appTheme=theme
  musicFixture()
  const wrapper=render(false,document.body);await flushPromises()
  try {
    for(const selector of ['.clip-audio','.clip-audio .editor-clip-handle.left']){
      await wrapper.get('.clip-audio').trigger('click')
      const event=new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true})
      wrapper.get(selector).element.dispatchEvent(event);await flushPromises()
      expect(event.defaultPrevented).toBe(true)
      expect(wrapper.findComponent(EditorTimeline).props('document').clips.map(clip=>clip.id)).toEqual(['v1','v2','v3'])
      expect(wrapper.findComponent(EditorLibrary).props('media')).toHaveLength(4)
      await wrapper.get('.editor-workspace').trigger('keydown',{key:'z',metaKey:true})
      expect(wrapper.findComponent(EditorTimeline).props('document').clips).toHaveLength(4)
    }
  } finally {wrapper.unmount()}
})
it.each(['Delete','Backspace'])('does not remove clips when editing text, outside the editor, read-only or holding the key (%s)',async key=>{
  musicFixture()
  const wrapper=render(false,document.body);await flushPromises()
  try {
    await wrapper.get('.clip-audio').trigger('click')
    for(const element of [wrapper.get('.editor-search input').element,document.body]){
      const event=new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true})
      element.dispatchEvent(event);await flushPromises()
      expect(event.defaultPrevented).toBe(false)
    }
    await wrapper.get('.clip-audio').trigger('keydown',{key,repeat:true})
    expect(wrapper.findComponent(EditorTimeline).props('document').clips).toHaveLength(4)
    useAuthStore().enabled=true;useAuthStore().memberships=[{team_id:1,role:'viewer'}] as never
    await wrapper.get('.clip-audio').trigger('keydown',{key})
    expect(wrapper.findComponent(EditorTimeline).props('document').clips).toHaveLength(4)
  } finally {wrapper.unmount()}
})

it('commits overlay positions through the preview contract and undo restores the original placement',async()=>{
 const wrapper=render();await flushPromises()
 wrapper.findComponent(EditorLibrary).vm.$emit('subtitle');await flushPromises()
 const clip=wrapper.findComponent(EditorInspector).props('clip')!
 wrapper.findComponent(EditorPreview).vm.$emit('position',clip.id,{x:25,bottom:40});await flushPromises()
 expect(wrapper.findComponent(EditorInspector).props('clip')).toMatchObject({x:25,bottom:40})
 wrapper.findComponent(EditorTimeline).vm.$emit('undo');await flushPromises()
 expect(wrapper.findComponent(EditorInspector).props('clip')).toMatchObject({bottom:10})
 wrapper.unmount()
})

it('undoes sticker size and rotation changes as a single transform',async()=>{
 const fixture=editorFixture()
 fixture.document.clips.push({id:'sticker',type:'sticker',name:'Sticker',source:{kind:'asset',id:9},start:0,duration:4,x:50,y:50,scale:1,opacity:1})
 fixture.media.push({key:'asset:9',source:{kind:'asset',id:9},kind:'sticker',name:'Sticker',url:'/sticker.png',width:80,height:40})
 vi.mocked(editorApi.get).mockResolvedValue({data:fixture} as never)
 const wrapper=render();await flushPromises()
 wrapper.findComponent(EditorPreview).vm.$emit('select','sticker');await flushPromises()
 wrapper.findComponent(EditorPreview).vm.$emit('position','sticker',{scale:2,scale_y:1,rotation:90});await flushPromises()
 expect(wrapper.findComponent(EditorInspector).props('clip')).toMatchObject({scale:2,scale_y:1,rotation:90})
 wrapper.findComponent(EditorTimeline).vm.$emit('undo');await flushPromises()
 expect(wrapper.findComponent(EditorInspector).props('clip')).toMatchObject({scale:1,x:50,y:50})
 wrapper.findComponent(EditorTimeline).vm.$emit('redo');await flushPromises()
 expect(wrapper.findComponent(EditorInspector).props('clip')).toMatchObject({scale:2,rotation:90})
 wrapper.unmount()
})

it('keeps the video track gapless when the frame rate changes', async () => {
  const fixture = editorFixture()
  fixture.document.clips[0]!.duration = 1 / 24
  fixture.document.clips[1]!.start = 1 / 24
  fixture.document.clips[1]!.duration = 2 / 24
  fixture.document.clips[2]!.start = 3 / 24
  vi.mocked(editorApi.get).mockResolvedValue({ data: fixture } as never)
  const wrapper = render()
  await flushPromises()
  const fps = wrapper.findAllComponents(AppSelect).find(select => select.props('ariaLabel') === 'FPS')
  fps!.vm.$emit('update:modelValue', '30')
  await flushPromises()
  const result = wrapper.findComponent(EditorTimeline).props('document')
  expect(result.fps).toBe(30)
  expect(result.clips.map(clip => Math.round(clip.start * result.fps))).toEqual([0, 1, 4])
  wrapper.unmount()
})

it.each(['light', 'dark'])('changes speed with the real inspector and saves without opening gaps (%s)', async theme => {
  document.documentElement.dataset.appTheme = theme
  const fixture = editorFixture()
  fixture.document.clips[0]!.duration = 8
  fixture.document.clips[1]!.start = 8
  fixture.document.clips[2]!.start = 10
  fixture.media[0]!.duration = 8
  vi.mocked(editorApi.get).mockResolvedValue({ data: fixture } as never)
  const wrapper = render()
  await flushPromises()
  const rate = wrapper.get('input[aria-label="倍速数值"]')
  const timeline = wrapper.findComponent(EditorTimeline)
  for (const speed of [2.82, 18.3, 1]) {
    await rate.setValue(speed)
    const [first, second] = timeline.props('document').clips
    expect(first).toMatchObject({ speed, trim_in: 0, trim_out: 8 })
    expect(second?.start).toBe(first!.duration)
  }
  await wrapper.get('button[aria-label="保存剪辑草稿"]').trigger('click')
  await flushPromises()
  expect(vi.mocked(editorApi.save).mock.lastCall?.[2].clips[0]).toMatchObject({ duration: 8, trim_out: 8 })
  wrapper.unmount()
})

it('clears existing subtitles and applies recognized speech segments when AI recognition completes', async () => {
  const fixture = editorFixture()
  // 增加一条旧字幕
  fixture.document.clips.push({
    id: 'old-sub-1',
    type: 'subtitle',
    name: '',
    start: 0,
    duration: 2,
    text: '旧字幕待清空',
    font: 'sans',
    font_size: 42,
    color: '#ffffff',
    bottom: 10,
  })
  vi.mocked(editorApi.get).mockResolvedValue({ data: fixture } as never)
  const recognizedDoc = JSON.parse(JSON.stringify(fixture.document)) as EditDocument
  recognizedDoc.clips = recognizedDoc.clips.filter(c => c.type !== 'subtitle')
  recognizedDoc.clips.push(
    {
      id: 'sub-new-1',
      type: 'subtitle',
      name: '',
      start: 0.2,
      duration: 1.5,
      text: '大家好今天给大家介绍一款软件',
      font: 'sans',
      font_size: 42,
      color: '#ffffff',
      bottom: 10,
    },
    {
      id: 'sub-new-2',
      type: 'subtitle',
      name: '',
      start: 1.8,
      duration: 2.1,
      text: '如果你平时有在做短视频',
      font: 'sans',
      font_size: 42,
      color: '#ffffff',
      bottom: 10,
    },
  )
  vi.mocked(editorApi.recognizeSubtitles).mockResolvedValue({
    code: 0,
    data: { document: recognizedDoc, subtitles_created: 2, revision: 2 },
  } as never)

  const wrapper = render()
  await flushPromises()

  // 触发 AI 识别
  wrapper.findComponent(EditorLibrary).vm.$emit('recognize')
  await flushPromises()

  expect(editorApi.recognizeSubtitles).toHaveBeenCalled()
  const timelineClips = wrapper.findComponent(EditorTimeline).props('document').clips
  const subClips = timelineClips.filter(c => c.type === 'subtitle')
  expect(subClips).toHaveLength(2)
  expect(subClips[0]).toMatchObject({ id: 'sub-new-1', text: '大家好今天给大家介绍一款软件' })
  expect(subClips[1]).toMatchObject({ id: 'sub-new-2', text: '如果你平时有在做短视频' })
  // 检查首个字幕被选中
  expect(wrapper.findComponent(EditorTimeline).props('selectedId')).toBe('sub-new-1')
  wrapper.unmount()
})

it('keeps edits made while speech recognition is pending',async()=>{
  let finish!: (value:never)=>void
  vi.mocked(editorApi.recognizeSubtitles).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve}))
  const wrapper=render();await flushPromises()
  wrapper.findComponent(EditorLibrary).vm.$emit('recognize');await flushPromises()
  wrapper.findComponent(EditorLibrary).vm.$emit('subtitle');await flushPromises()
  const before=JSON.stringify(wrapper.findComponent(EditorTimeline).props('document'))
  finish({data:{document:editorFixture().document,subtitles_created:0,revision:1}} as never)
  await flushPromises()
  expect(JSON.stringify(wrapper.findComponent(EditorTimeline).props('document'))).toBe(before)
  wrapper.unmount()
})

it.each(['light','dark'])('applies multi-clip volume changes without pausing and undoes the gesture once (%s)',async theme=>{
  document.documentElement.dataset.appTheme=theme
  const fixture=editorFixture()
  const music:AudioClip={id:'music',type:'audio',name:'BGM',source:{kind:'asset',id:5},start:0,duration:6,volume:.4,trim_in:0,fade_in:0,fade_out:0,loop:false}
  fixture.document.clips.push(music)
  vi.mocked(editorApi.get).mockResolvedValue({data:fixture} as never)
  const wrapper=render();await flushPromises()
  wrapper.findComponent(EditorTimeline).vm.$emit('selectMany',['v1','music']);await flushPromises()
  expect(wrapper.findComponent(EditorInspector).props('clip')).toMatchObject({id:'v1',volume:1})
  expect(wrapper.findComponent(EditorInspector).props('selectionCount')).toBe(2)
  wrapper.findComponent(EditorPreview).vm.$emit('update:playing',true);await flushPromises()
  const inspector=wrapper.findComponent(EditorInspector)
  inspector.vm.$emit('editStart')
  for(let i=0;i<50;i++)inspector.vm.$emit('change',{volume:.2+i/1000})
  inspector.vm.$emit('editEnd');await flushPromises()
  expect(wrapper.find('.editor-transport button[aria-label="暂停"]').exists()).toBe(true)
  const clips=wrapper.findComponent(EditorTimeline).props('document').clips
  expect(clips.find(c=>c.id==='v1')).toMatchObject({volume:.249})
  expect(clips.find(c=>c.id==='music')).toMatchObject({volume:.249})
  expect(clips.find(c=>c.id==='v2')).toMatchObject({volume:1})
  wrapper.findComponent(EditorTimeline).vm.$emit('undo');await flushPromises()
  const restored=wrapper.findComponent(EditorTimeline).props('document').clips
  expect(restored.find(c=>c.id==='v1')).toMatchObject({volume:1})
  expect(restored.find(c=>c.id==='music')).toMatchObject({volume:.4})
  wrapper.unmount()
})

it('uses the first selected subtitle as the initial style and preserves other text when batch formatting',async()=>{
  const fixture=editorFixture()
  fixture.document.clips.push(...[{id:'a',font_size:35,text:'First'},{id:'b',font_size:60,text:'Second'}].map(item=>({...item,type:'subtitle' as const,name:'',start:0,duration:1,font:'sans' as const,color:'#ffffff',bottom:10})))
  vi.mocked(editorApi.get).mockResolvedValue({data:fixture} as never)
  const wrapper=render();await flushPromises()
  wrapper.findComponent(EditorTimeline).vm.$emit('selectMany',['b','a']);await flushPromises()
  expect(wrapper.findComponent(EditorInspector).props('clip')).toMatchObject({id:'b',font_size:60,text:'Second'})
  wrapper.findComponent(EditorInspector).vm.$emit('change',{font_size:48,bold:true});await flushPromises()
  const subtitles=wrapper.findComponent(EditorTimeline).props('document').clips.filter(c=>c.type==='subtitle')
  expect(subtitles.map(c=>c.text)).toEqual(['First','Second'])
  expect(subtitles.every(c=>c.font_size===48&&c.bold)).toBe(true)
  wrapper.findComponent(EditorTimeline).vm.$emit('remove');await flushPromises()
  expect(wrapper.findComponent(EditorTimeline).props('document').clips.filter(c=>c.type==='subtitle')).toHaveLength(0)
  wrapper.unmount()
})

it('splits existing long subtitles through the local endpoint and preserves undo without ASR calls',async()=>{
  const fixture=editorFixture(),long='这是一段较长的字幕内容'.repeat(5)
  const subtitle={id:'s',type:'subtitle' as const,name:'',start:0,duration:6,text:long,font:'sans' as const,font_size:48,color:'#ffffff',bottom:10}
  fixture.document.clips.push(subtitle)
  const result={...fixture.document,clips:[...fixture.document.clips.filter(c=>c.type!=='subtitle'),{...subtitle,text:'第一句',duration:3},{...subtitle,id:'s2',text:'第二句',start:3,duration:3}]}
  vi.mocked(editorApi.get).mockResolvedValue({data:fixture} as never)
  vi.mocked(editorApi.splitSubtitles).mockResolvedValue({data:{document:result,split_count:1}} as never)
  const wrapper=render();await flushPromises()
  wrapper.findComponent(EditorLibrary).vm.$emit('splitSubtitles');await flushPromises()
  expect(editorApi.splitSubtitles).toHaveBeenCalledWith(450,expect.any(Object),undefined)
  expect(editorApi.recognizeSubtitles).not.toHaveBeenCalled()
  expect(wrapper.findComponent(EditorTimeline).props('document').clips.filter(c=>c.type==='subtitle')).toHaveLength(2)
  wrapper.findComponent(EditorTimeline).vm.$emit('undo');await flushPromises()
  expect(wrapper.findComponent(EditorTimeline).props('document').clips.find(c=>c.id==='s')).toMatchObject({text:long,font_size:48})
  wrapper.unmount()
})
