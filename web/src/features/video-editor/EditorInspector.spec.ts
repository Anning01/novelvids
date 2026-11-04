import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import EditorInspector from './EditorInspector.vue'
import { editorFixture } from './fixtures'
it.each(['light','dark'])('shows media information, dB gain, a precise speed slider and rotation (%s)',async theme=>{
 document.documentElement.dataset.appTheme=theme
 const fixture=editorFixture()
 const wrapper=mount(EditorInspector,{props:{clip:fixture.document.clips[0]!,media:{...fixture.media[0]!,width:1920,height:1080,fps:24},readOnly:false,open:true}})
 expect(wrapper.text()).toContain('1920 × 1080')
 expect((wrapper.get('input[aria-label="音量数值"]').element as HTMLInputElement).value).toBe('0')
 expect(wrapper.get('.editor-number-unit').text()).toContain('×')
 for(const text of ['移动片段','在分镜中查看','替换为此分镜当前视频','入点','出点','适应画布','填满画布'])expect(wrapper.text()).not.toContain(text)
 const rate=wrapper.get('input[aria-label="倍数"]')
 expect(rate.attributes()).toMatchObject({type:'range',min:'.1',max:'20',step:'.01'})
 await wrapper.get('input[aria-label="倍速数值"]').setValue('8.74')
 expect(wrapper.emitted('trim')?.at(-1)).toEqual([0,2,8.74])
 await wrapper.get('input[aria-label="音量"]').setValue(20)
 expect(wrapper.emitted('change')?.at(-1)).toEqual([{volume:10}])
 await wrapper.get('input[aria-label="音量数值"]').setValue(-20)
 expect(wrapper.emitted('change')?.at(-1)).toEqual([{volume:.1}])
 await wrapper.get('input[aria-label="旋转角度"]').setValue(-5)
 expect(wrapper.emitted('change')?.at(-1)).toEqual([{rotation:-5}])
 await wrapper.findAll('button').find(button=>button.text()==='重置画面')!.trigger('click')
 expect(wrapper.emitted('change')?.at(-1)).toEqual([{scale:1,fit:'contain',rotation:0}])
})
it('disables editing controls for viewers',()=>{
 const wrapper=mount(EditorInspector,{props:{clip:editorFixture().document.clips[0]!,readOnly:true,open:true}})
 expect(wrapper.get('fieldset').attributes('disabled')).toBeDefined()
})

it.each(['light','dark'])('edits subtitle formatting, thirteen presets and opacity without timeline controls (%s)',async theme=>{
 document.documentElement.dataset.appTheme=theme
 const {readFileSync}=await import('node:fs')
 const presets=JSON.parse(readFileSync('../seeds/subtitle_styles.json','utf8')) as import('./types').SubtitlePreset[]
 const clip:import('./types').SubtitleClip={id:'s',type:'subtitle',name:'',start:0,duration:3,text:'字幕内容',font:'sans',font_size:42,color:'#ffffff',bottom:10}
 const wrapper=mount(EditorInspector,{props:{clip,subtitleStyles:presets,readOnly:false,open:true}})
 expect(wrapper.text()).not.toContain('素材信息')
 expect(wrapper.text()).not.toContain('时长')
 expect(wrapper.findAll('.editor-subtitle-preset')).toHaveLength(14)
 for(const [label,patch] of [['加粗',{bold:true}],['下划线',{underline:true}],['斜体',{italic:true}],['右对齐',{align:'right'}]] as const){
  await wrapper.get(`button[aria-label="${label}"]`).trigger('click')
  expect(wrapper.emitted('change')?.at(-1)).toEqual([patch])
 }
 await wrapper.get('input[aria-label="字幕透明度"]').setValue(.35)
 expect(wrapper.emitted('change')?.at(-1)).toEqual([{opacity:.35}])
 await wrapper.get('input[aria-label="字号数值"]').setValue(90)
 expect(wrapper.emitted('change')?.at(-1)).toEqual([{font_size:90}])
 const preset=presets.find(preset=>preset.id==='yellow-black')!
 await wrapper.get(`button[aria-label="${preset.name}"]`).trigger('click')
 expect(wrapper.emitted('change')?.at(-1)).toEqual([{color:preset.color,bold:preset.bold,stroke_color:preset.stroke_color,stroke_width:preset.stroke_width,shadow:preset.shadow}])
 await wrapper.setProps({clip:{...clip,...preset}})
 expect(wrapper.get(`button[aria-label="${preset.name}"]`).attributes('aria-pressed')).toBe('true')
})

it.each(['light','dark'])('keeps sticker controls limited to scale, aspect lock, opacity and reset (%s)',async theme=>{
 document.documentElement.dataset.appTheme=theme
 const clip:import('./types').StickerClip={id:'i',name:'Sticker',type:'sticker',start:0,duration:4,source:{kind:'asset',id:1},x:25,y:35,scale:2,scale_y:1,lock_aspect:false,rotation:45,opacity:.5}
 const wrapper=mount(EditorInspector,{props:{clip,readOnly:false,open:true}})
 for(const label of ['素材信息','开始（秒）','移动片段','X %','Y %','旋转角度'])expect(wrapper.text()).not.toContain(label)
 expect(wrapper.findAll('input[type="range"]')).toHaveLength(2)
 await wrapper.get('input[aria-label="贴纸缩放"]').setValue(1.5)
 expect(wrapper.emitted('change')?.at(-1)).toEqual([{scale:1.5}])
 await wrapper.get('input[aria-label="等比缩放"]').setValue(true)
 expect(wrapper.emitted('change')?.at(-1)).toEqual([{lock_aspect:true,scale_y:1}])
 await wrapper.findAll('button').find(button=>button.text()==='重置贴纸')!.trigger('click')
 expect(wrapper.emitted('change')?.at(-1)).toEqual([{x:50,y:50,scale:1,scale_y:null,lock_aspect:true,rotation:0,opacity:1}])
})

it('ends an input gesture after native change and marks mixed selection text replacement explicitly',async()=>{
  const clip={id:'s',type:'subtitle' as const,name:'',start:0,duration:2,text:'First',font:'sans' as const,font_size:42,color:'#ffffff',bottom:10}
  const wrapper=mount(EditorInspector,{props:{clip,selectionCount:5,readOnly:false,open:true}})
  expect(wrapper.text()).toContain('修改内容会替换所有选中字幕的文字。')
  await wrapper.get('[aria-label="字号"]').trigger('pointerdown')
  await wrapper.get('[aria-label="字号"]').setValue(36)
  await wrapper.vm.$nextTick()
  expect(wrapper.emitted('editStart')).toHaveLength(1)
  expect(wrapper.emitted('editEnd')).toHaveLength(1)
  expect(wrapper.emitted('change')?.at(-1)).toEqual([{font_size:36}])
  wrapper.unmount()
})

it.each(['light','dark'])('uses the shared font selector for batch caption editing (%s)',async theme=>{
  const { default:AppSelect }=await import('@/components/AppSelect.vue')
  const { default:AppButton }=await import('@/components/AppButton.vue')
  document.documentElement.dataset.appTheme=theme
  const clip={id:'s',type:'subtitle' as const,name:'',start:0,duration:2,text:'测试',font:'sans',font_size:42,color:'#ffffff',bottom:10}
  const wrapper=mount(EditorInspector,{props:{clip,selectionCount:2,readOnly:false,open:true,subtitleFonts:[{value:'sans',label:'系统中文黑体'},{value:'source-han-serif',label:'思源宋体'}]},global:{components:{AppButton}}})
  const picker=wrapper.getComponent(AppSelect)
  expect(picker.props('modelValue')).toBe('sans')
  await picker.get('button').trigger('click')
  const option=Array.from(document.querySelectorAll<HTMLButtonElement>('[role="option"]')).find(el=>el.textContent?.trim()==='思源宋体')!
  option.click()
  expect(wrapper.emitted('change')?.at(-1)).toEqual([{font:'source-han-serif'}])
  await wrapper.setProps({readOnly:true})
  expect(picker.get('button').attributes('disabled')).toBeDefined()
  wrapper.unmount()
})
