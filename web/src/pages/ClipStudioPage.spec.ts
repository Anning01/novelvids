import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import ClipStudioPage from './ClipStudioPage.vue'
import { api, ApiRequestError } from '@/api'
import { useAuthStore } from '@/features/auth/authStore'
import { clipApi, type ClipSession } from '@/features/creation-agent/clipApi'
import { useCreationAgentStore } from '@/features/creation-agent/store'
import type { AgentRun } from '@/features/creation-agent/types'
import type { Scene, Video } from '@/types'

vi.mock('@/features/creation-agent/CreationAgentPanel.vue', () => ({default: {props:['initialConversationId','initialUserText'],template:'<aside aria-label="创作助手">{{ initialUserText }}</aside>'}}))

const ok = <T,>(data: T) => ({code:0, message:'ok', data})
const page = <T,>(items: T[]) => ok({items, pagination:{total:items.length,page:1,page_size:100,pages:1}})
const session: ClipSession = { project_id:17, chapter_id:20, scene_id:30, asset_id:null, conversation_id:40,
  request_id:'test', task_type:'video', mode:'agent', model_config_id:2, assistant_model_config_id:7, image_model_config_id:null,
  prompt:'雨中的街角', name:'雨中的街角', aspect_ratio:'16:9', resolution:'720p', duration:5, model_name:'真实配置模型', reference_media:[], created_at:'' }
const shot = {id:30, sequence:1, chapter_id:20, prompt:'已保存的完整提示词', description:'街角', created_at:'', updated_at:''} as Scene
let wrapper: ReturnType<typeof mount> | undefined
beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(clipApi,'session').mockImplementation(async () => ok({...session,reference_media:[...session.reference_media]}))
  vi.spyOn(clipApi,'start').mockResolvedValue(ok({task_id:'task'} as AgentRun))
  vi.spyOn(api,'scenes').mockResolvedValue(page([shot]))
  vi.spyOn(api,'assets').mockResolvedValue(page([]))
  vi.spyOn(api,'videoGenerationHistory').mockResolvedValue(ok([]))
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined })
async function render(start=false) {
  const router = createRouter({history:createMemoryHistory(), routes:[{path:'/create/clip/:projectId',name:'clip-studio',component:{template:'<div/>'}},{path:'/',component:{template:'<div/>'}}]})
  await router.push('/create/clip/17' + (start ? '?start=1' : '')); await router.isReady()
  const pinia = createPinia()
  wrapper = mount(ClipStudioPage,{global:{plugins:[pinia,router],stubs:{CreationAgentPanel:{props:['initialConversationId','initialUserText'],template:'<aside aria-label="创作助手">{{ initialUserText }}</aside>'}}}})
  await flushPromises()
  return {wrapper,router,store:useCreationAgentStore(pinia)}
}
it('starts once, enters a real conversation and clears the auto-start URL', async () => {
  const {wrapper,router} = await render(true)
  expect(clipApi.start).toHaveBeenCalledExactlyOnceWith(17)
  expect(router.currentRoute.value.query.start).toBeUndefined()
  expect(wrapper.get('[aria-label="创作助手"]').text()).toBe(session.prompt)
  expect(wrapper.text()).toContain('已保存的完整提示词')
  expect(wrapper.find('.showcase-section').exists()).toBe(false)
})
it('restores a previous session without resubmitting generation',async () => {
  const {wrapper} = await render()
  expect(clipApi.start).not.toHaveBeenCalled()
  expect(wrapper.find('video').exists()).toBe(false)
  expect(wrapper.text()).toContain('在左侧完善镜头')
})
it('shows only completed real media and displays failures separately',async () => {
  vi.mocked(api.videoGenerationHistory).mockResolvedValue(ok([
    {id:1,scene_id:30,status:3,url:'/media/actual.mp4',metadata:{},created_at:'',updated_at:''},
    {id:2,scene_id:30,status:4,metadata:{error:'供应商拒绝请求'},created_at:'',updated_at:''},
  ] as Video[]))
  const {wrapper} = await render()
  expect(wrapper.findAll('video')).toHaveLength(1)
  expect(wrapper.get('video').attributes('src')).toContain('/media/actual.mp4')
  expect(wrapper.text()).toContain('供应商拒绝请求')
  expect(wrapper.get('video').attributes('style')).toMatch(/aspect-ratio:\s*16\s*\/\s*9/)
})
it('keeps the workspace and saved content visible after start failure',async () => {
  vi.mocked(clipApi.start).mockRejectedValue(new Error('模型已停用'))
  const {wrapper} = await render(true)
  expect(wrapper.get('[role="alert"]').text()).toContain('模型已停用')
  expect(wrapper.find('[aria-label="创作助手"]').exists()).toBe(true)
  expect(wrapper.text()).toContain('已保存的完整提示词')
  expect(wrapper.text()).toContain('你的描述、参考素材和生成参数已保存')
  expect(wrapper.text()).toContain('重试')
})
it('submits explicit generation intent with the selected model and ratio',async () => {
  const {wrapper,store} = await render()
  const send = vi.spyOn(store,'send').mockResolvedValue(true)
  const button = wrapper.findAll('button').find(item=>item.text()==='生成视频')!
  await button.trigger('click'); await flushPromises()
  expect(send).toHaveBeenCalledWith(expect.objectContaining({production_intents:[expect.objectContaining({operation:'video',target_id:30,media_model_config_id:2,video_options:expect.objectContaining({aspect_ratio:'16:9',duration:5,resolution:'720p'})})]}))
})


it('keeps insufficient-credit recovery inside the workspace and offers an account action', async () => {
  vi.mocked(clipApi.start).mockRejectedValue(new ApiRequestError('团队余额不足，请联系团队管理员充值',402,402))
  const {wrapper,store} = await render(true)
  const auth = useAuthStore()
  auth.enabled = true
  auth.user = {id:1,username:'creator',nickname:'创作者',avatar_url:'',is_super_admin:false}
  auth.activeTeamId = 1
  auth.memberships = [{team_id:1,team_name:'团队',role:'creator'}]
  await flushPromises()
  expect(wrapper.find('.studio-layout').exists()).toBe(true)
  expect(wrapper.get('.studio-start-notice').text()).toContain('余额不足')
  expect(wrapper.get('.start-notice-actions a').attributes('href')).toContain('/profile')
  expect(wrapper.get('.start-notice-actions a').text()).toContain('充值')
  expect(wrapper.text()).toContain('已保存的完整提示词')
  const send = vi.spyOn(store,'send')
  expect(wrapper.findAll('button').find(button => button.text()==='生成视频')!.attributes('disabled')).toBeDefined()
  expect(send).not.toHaveBeenCalled()
  vi.mocked(clipApi.start).mockResolvedValue(ok({task_id:'resumed',conversation_id:41,status:2} as AgentRun))
  await wrapper.findAll('button').find(button => button.text()==='处理后继续创作')!.trigger('click')
  await flushPromises()
  expect(wrapper.find('.studio-start-notice').exists()).toBe(false)
  expect(wrapper.find('.studio-layout').exists()).toBe(true)
})

it('distinguishes personal spending limits from team balance', async () => {
  vi.mocked(clipApi.start).mockRejectedValue(new ApiRequestError('你已达到个人消费限额，请联系团队管理员调整',402,402))
  const {wrapper} = await render(true)
  expect(wrapper.get('.studio-start-notice h2').text()).toBe('个人额度已用完')
  expect(wrapper.get('.start-notice-actions a').text()).toBe('查看我的额度')
  expect(wrapper.get('.studio-start-notice').text()).not.toContain('充值')
})
