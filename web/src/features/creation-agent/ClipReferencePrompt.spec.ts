import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, expect, it } from 'vitest'
import ClipReferencePrompt from './ClipReferencePrompt.vue'
import { nameClipReference, displayClipPrompt } from './clipReferences'
import type { VideoReferenceMedia } from '@/types'

const references: VideoReferenceMedia[] = [
  {type:'image',url:'/media/a.png',name:'a.png',mention_name:'图片1'},
  {type:'image',url:'/media/b.png',name:'b.png',mention_name:'图片2'},
]
beforeEach(() => {
  Object.defineProperty(Range.prototype,'getBoundingClientRect',{configurable:true,value:()=>({top:20,left:20,right:20,bottom:40,width:0,height:20,x:20,y:20,toJSON:()=>({})})})
})
function render(modelValue='') {
  return mount(ClipReferencePrompt,{attachTo:document.body,props:{modelValue,references}})
}
it('uses the canvas mention picker, supports keyboard selection and inserts a named token',async()=>{
  const wrapper=render()
  await flushPromises()
  const input=wrapper.get('[role="textbox"]').element as HTMLDivElement
  input.focus();input.textContent='使用 @'
  const range=document.createRange();range.selectNodeContents(input);range.collapse(false)
  window.getSelection()?.removeAllRanges();window.getSelection()?.addRange(range)
  input.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:'@'}))
  await wrapper.setProps({modelValue:'使用 @'})
  await flushPromises()
  expect(wrapper.get('[role="listbox"]').text()).toContain('图片1')
  expect(wrapper.findAll('[role="option"]')).toHaveLength(2)
  await wrapper.get('[role="textbox"]').trigger('keydown',{key:'ArrowDown'})
  await wrapper.get('[role="textbox"]').trigger('keydown',{key:'Enter'})
  expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['使用 @{图片2} '])
})
it('inserts an uploaded image by clicking its simple thumbnail',async()=>{
  const wrapper=render('镜头中的人物')
  await flushPromises()
  await wrapper.get('[aria-label="引用 图片1"]').trigger('click')
  expect(wrapper.emitted('update:modelValue')?.at(-1)?.[0]).toContain('@{图片1}')
  expect(wrapper.findAll('.clip-reference-insert img')).toHaveLength(2)
})
it('removing a material clears its mention while retaining other text and references',async()=>{
  const wrapper=render('用 @{图片1} 的构图和 @{图片2} 的光线。')
  await wrapper.setProps({references:[references[1]!]});await flushPromises()
  const value=wrapper.emitted('update:modelValue')?.at(-1)?.[0] as string
  expect(value).not.toContain('@{图片1}')
  expect(value).toContain('@{图片2}')
  expect(value).toContain('的构图和')
})
it('names opaque uploads clearly and disambiguates file names',()=>{
  const first=nameClipReference({type:'image',url:'/a',name:'feb6b1f2b226c59c7ca16364750c7806.jpg'},[])
  expect(first.mention_name).toBe('图片1')
  const second=nameClipReference({type:'image',url:'/b',name:'feb6b1f2b226c59c7ca16364750c7806.jpg'},[first])
  expect(second.mention_name).toBe('图片2')
  const named=nameClipReference({type:'image',url:'/c',name:'女主.png'},[])
  expect(nameClipReference({type:'image',url:'/d',name:'女主.jpg'},[named]).mention_name).toBe('女主 2')
})
it('reports long descriptions without silently truncating them',async()=>{
  const wrapper=render('字'.repeat(4001))
  expect(wrapper.get('[role="alert"]').text()).toContain('4000')
  expect(wrapper.emitted('update:modelValue')).toBeUndefined()
})

it('submits the keyboard shortcut only after IME composition completes',async()=>{
  const wrapper=render('保留输入')
  await wrapper.get('[role="textbox"]').trigger('keydown',{key:'Enter',ctrlKey:true,isComposing:true})
  expect(wrapper.emitted('submit')).toBeUndefined()
  await wrapper.get('[role="textbox"]').trigger('keydown',{key:'Enter',ctrlKey:true,isComposing:false})
  expect(wrapper.emitted('submit')).toHaveLength(1)
})

it('displays saved protocol references as readable material names without changing prose',()=>{
  expect(displayClipPrompt('保持 @{参考图片:%2Fmedia%2Fa.png} 的构图。',references)).toBe('保持 @{图片1} 的构图。')
})
