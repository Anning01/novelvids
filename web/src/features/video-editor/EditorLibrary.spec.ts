import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import EditorLibrary from './EditorLibrary.vue'

afterEach(()=>vi.restoreAllMocks())

describe('EditorLibrary', () => {
  it('renders AI recognition button in subtitle tab and handles click event (dark)', async () => {
    document.documentElement.classList.add('dark')
    const wrapper = mount(EditorLibrary, {
      props: {
        media: [],
        busy: false,
        progress: 0,
        readOnly: false,
        recognizing: false,
      },
    })

    // 切换到字幕 Tab (第三个 tab 按钮)
    const subtitleTabBtn = wrapper.findAll('.editor-library-nav button')[2]
    expect(subtitleTabBtn).toBeDefined()
    await subtitleTabBtn.trigger('click')

    // 检查按钮存在
    const aiBtn = wrapper.find('.editor-ai-btn')
    expect(aiBtn.exists()).toBe(true)
    expect(aiBtn.text()).toContain('AI 识别')
    expect(aiBtn.attributes('disabled')).toBeUndefined()

    // 点击触发 recognize 事件
    await aiBtn.trigger('click')
    expect(wrapper.emitted('recognize')).toHaveLength(1)
  })

  it('disables AI recognition button and displays loading text when recognizing (light)', async () => {
    document.documentElement.classList.remove('dark')
    const wrapper = mount(EditorLibrary, {
      props: {
        media: [],
        busy: false,
        progress: 0,
        readOnly: false,
        recognizing: true,
      },
    })

    const subtitleTabBtn = wrapper.findAll('.editor-library-nav button')[2]
    await subtitleTabBtn.trigger('click')

    const aiBtn = wrapper.find('.editor-ai-btn')
    expect(aiBtn.exists()).toBe(true)
    expect(aiBtn.text()).toContain('识别中...')
    expect(aiBtn.attributes('disabled')).toBeDefined()
  })
})


it.each(['light','dark'])('keeps audio auditions in the library footer (%s)',async theme=>{
  document.documentElement.dataset.appTheme=theme
  const play=vi.spyOn(HTMLMediaElement.prototype,'play').mockResolvedValue()
  const name='An extremely long music title '.repeat(10)
  const item={key:'asset:12',source:{kind:'asset' as const,id:12},kind:'audio' as const,name,url:'/music.mp3',duration:60}
  const wrapper=mount(EditorLibrary,{props:{media:[item],busy:false,progress:0,readOnly:false}})
  await wrapper.findAll('.editor-library-nav button')[1]!.trigger('click')
  await wrapper.get('.editor-media-thumb').trigger('click')
  expect(wrapper.emitted('select')).toBeUndefined()
  expect(play).toHaveBeenCalledTimes(1)
  await wrapper.get('.editor-media-thumb').trigger('click')
  expect(play).toHaveBeenCalledTimes(2)
  expect(wrapper.get('.editor-library-audition audio').attributes('src')).toContain('/music.mp3')
  expect(wrapper.get('.editor-library-audition audio').attributes('controls')).toBeDefined()
  expect(wrapper.get('.editor-media-label>span').attributes('title')).toBe(name)
  await wrapper.get('.editor-library-audition audio').trigger('error')
  expect(wrapper.get('[role="alert"]').text()).toContain('音频读取失败')
  await wrapper.get('[aria-label="关闭试听"]').trigger('click')
  expect(wrapper.find('audio').exists()).toBe(false)
  wrapper.unmount()
})

it('uses the same footer for team audio auditions while team video still opens the preview',async()=>{
  vi.spyOn(HTMLMediaElement.prototype,'play').mockResolvedValue()
  const item={key:'library:12',source:{kind:'library' as const,id:12},kind:'audio' as const,name:'Team music',url:'/music.mp3',duration:60}
  const wrapper=mount(EditorLibrary,{props:{media:[],busy:false,progress:0,readOnly:false},global:{stubs:{TeamResourcePanel:true}}})
  await wrapper.findAll('.editor-library-nav button')[1]!.trigger('click')
  await wrapper.findAll('.editor-source-tabs button').at(-1)!.trigger('click')
  wrapper.findComponent({name:'TeamResourcePanel'}).vm.$emit('select',item)
  await wrapper.vm.$nextTick()
  expect(wrapper.find('audio').exists()).toBe(true)
  expect(wrapper.emitted('select')).toBeUndefined()
  wrapper.findComponent({name:'TeamResourcePanel'}).vm.$emit('select',{...item,kind:'video'})
  await wrapper.vm.$nextTick()
  expect(wrapper.emitted('select')).toHaveLength(1)
  wrapper.unmount()
})


it('shows audio playback rejection in the library footer',async()=>{
  vi.spyOn(HTMLMediaElement.prototype,'play').mockRejectedValue(new Error('Playback blocked'))
  const item={key:'asset:1',source:{kind:'asset' as const,id:1},kind:'audio' as const,name:'Music',url:'/music.mp3',duration:60}
  const wrapper=mount(EditorLibrary,{props:{media:[item],busy:false,progress:0,readOnly:false}})
  await wrapper.findAll('.editor-library-nav button')[1]!.trigger('click')
  await wrapper.get('.editor-media-thumb').trigger('click')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('音频播放失败')
  expect(wrapper.emitted('select')).toBeUndefined()
  wrapper.unmount()
})
