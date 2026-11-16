import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import StoryboardSheetHistory from './StoryboardSheetHistory.vue'
import { api } from '@/api'
import type { Scene } from '@/types'
vi.mock('@/api',()=>({mediaUrl:(url:string)=>url,api:{storyboardSheetHistory:vi.fn(),restoreStoryboardSheet:vi.fn()}}))
const scene={id:1,sequence:5,created_at:'',updated_at:''} as Scene
const history={scene_id:1,revision:'r1',current_image_url:'/new.png',items:[
  {task_id:'new',source:false,image_url:'/new.png',is_current:true,instruction:'调整站位',created_at:'2026-01-01',saved:true},
  {task_id:'old',source:false,image_url:'/old.png',is_current:false,instruction:'',created_at:'2026-01-01',saved:true},
]}
beforeEach(()=>{vi.clearAllMocks();vi.mocked(api.storyboardSheetHistory).mockResolvedValue({code:0,message:'',data:history})})
it.each(['light','dark'])('compares and restores the selected task without image generation (%s)',async theme=>{
  document.documentElement.dataset.appTheme=theme
  vi.mocked(api.restoreStoryboardSheet).mockResolvedValue({code:0,message:'',data:{...scene,metadata:{storyboard_sheet:{image_url:'/old.png'}}}})
  const wrapper=mount(StoryboardSheetHistory,{attachTo:document.body,props:{open:true,scene}})
  const screen=new DOMWrapper(document.body)
  await flushPromises()
  expect(screen.findAll('.sheet-history li')).toHaveLength(2)
  await screen.get('[aria-label="与当前线稿对比"]').trigger('click')
  await flushPromises()
  expect(screen.get('.image-lightbox').text()).toContain('2 / 2')
  await screen.get('[aria-label="关闭大图"]').trigger('click')
  await flushPromises()
  await screen.findAll('.sheet-history li')[1]!.get('.app-button').trigger('click')
  await flushPromises()
  expect(api.restoreStoryboardSheet).toHaveBeenCalledWith(1,{task_id:'old',source:false,expected_revision:'r1'})
  expect(wrapper.emitted('updated')?.[0]?.[0]).toMatchObject({id:1,metadata:{storyboard_sheet:{image_url:'/old.png'}}})
  delete document.documentElement.dataset.appTheme
})
it('shows recoverable loading failures without changing the current image',async()=>{
  vi.mocked(api.storyboardSheetHistory).mockRejectedValue(new Error('暂时无法读取'))
  const wrapper=mount(StoryboardSheetHistory,{props:{open:true,scene},global:{stubs:{Teleport:true}}})
  await flushPromises()
  expect(wrapper.get('[role=alert]').text()).toContain('暂时无法读取')
  expect(api.restoreStoryboardSheet).not.toHaveBeenCalled()
})
