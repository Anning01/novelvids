import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import VideoEnhanceButton from './VideoEnhanceButton.vue'
import { useAuthStore } from '@/features/auth/authStore'
import type { Video } from '@/types'

vi.mock('./ChapterExportPanel.vue', () => ({ default: defineComponent({ props:['videoId'], template:'<p>Video {{ videoId }}</p>' }) }))
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
  expect(document.querySelector('[role="dialog"]')).toBeNull()
  expect(document.activeElement).toBe(trigger.element)
  wrapper.unmount()
})

it('disables a real 1080p video and hides the action from viewers and unfinished videos', async () => {
  const pinia=createPinia()
  const wrapper=mount(VideoEnhanceButton,{props:{video:{...video,metadata:{width:1920,height:1080}}},global:{plugins:[pinia]}})
  expect(wrapper.get('button').attributes('disabled')).toBeDefined()
  expect(wrapper.text()).toContain('已达1080p')
  await wrapper.setProps({video:{...video,status:2}})
  expect(wrapper.find('button').exists()).toBe(false)
  await wrapper.setProps({video})
  const auth=useAuthStore(pinia)
  auth.$patch({enabled:true,user:{id:1,username:'viewer',nickname:'',avatar_url:'',is_super_admin:false},activeTeamId:1,memberships:[{team_id:1,team_name:'Team',role:'viewer'}]})
  await flushPromises()
  expect(wrapper.find('button').exists()).toBe(false)
  wrapper.unmount()
})
