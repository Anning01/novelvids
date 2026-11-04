import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import VideoEnhanceButton from './VideoEnhanceButton.vue'
import { useAuthStore } from '@/features/auth/authStore'
import type { Video } from '@/types'

vi.mock('./VideoEnhancementPanel.vue', () => ({ default: defineComponent({ props:['video'], emits:['close','applied'], template:'<div><button aria-label="关闭" @click="$emit(\'close\')">Close</button><p>Video {{ video.id }}</p><button aria-label="完成" @click="$emit(\'applied\',12)">Done</button></div>' }) }))
afterEach(() => { document.body.innerHTML = '' })
const video: Video = { id:9, scene_id:1, status:3, model_type:1, url:'/media/9.mp4', created_at:'', updated_at:'' }

it('opens the same video-specific dialog from either caller and preserves keyboard focus', async () => {
  const wrapper=mount(VideoEnhanceButton,{attachTo:document.body,props:{video},global:{plugins:[createPinia()]}})
  const trigger=wrapper.get('button')
  ;(trigger.element as HTMLButtonElement).focus()
  await trigger.trigger('click')
  await flushPromises()
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain('Video 9')
  const close=document.querySelector<HTMLButtonElement>('[aria-label="关闭"]')!
  expect(document.activeElement).toBe(close)
  close.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))
  await flushPromises()
  expect((document.querySelector('[role="dialog"]')?.parentElement as HTMLElement).style.display).toBe('none')
  expect(document.activeElement).toBe(trigger.element)
  wrapper.unmount()
})

it('keeps HD sources open for higher configured targets and hides the action from viewers and unfinished videos', async () => {
  const pinia=createPinia()
  const wrapper=mount(VideoEnhanceButton,{props:{video:{...video,metadata:{width:1920,height:1080}}},global:{plugins:[pinia]}})
  expect(wrapper.get('button').attributes('disabled')).toBeUndefined()
  expect(wrapper.text()).toContain('高清化')
  await wrapper.setProps({video:{...video,status:2}})
  expect(wrapper.find('button').exists()).toBe(false)
  await wrapper.setProps({video})
  const auth=useAuthStore(pinia)
  auth.$patch({enabled:true,user:{id:1,username:'viewer',nickname:'',avatar_url:'',is_super_admin:false},activeTeamId:1,memberships:[{team_id:1,team_name:'Team',role:'viewer'}]})
  await flushPromises()
  expect(wrapper.find('button').exists()).toBe(false)
  wrapper.unmount()
})

it('keeps the dialog open for its own applied result but closes on an unrelated video change', async () => {
  const wrapper=mount(VideoEnhanceButton,{attachTo:document.body,props:{video},global:{plugins:[createPinia()]}})
  await wrapper.get('button').trigger('click'); await flushPromises()
  document.querySelector<HTMLButtonElement>('[aria-label="完成"]')!.click(); await flushPromises()
  await wrapper.setProps({video:{...video,id:12}})
  expect((document.querySelector('[role="dialog"]')?.parentElement as HTMLElement).style.display).not.toBe('none')
  expect(wrapper.emitted('applied')).toEqual([[12]])
  await wrapper.setProps({video:{...video,id:20}})
  expect(document.querySelector('[role="dialog"]')).toBeNull()
  wrapper.unmount()
})
