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
import type { Asset, AssetGenerationRecord, BillingRecord, Scene, Video } from '@/types'

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
  vi.spyOn(api,'assetGenerationHistory').mockResolvedValue(ok([]))
  vi.spyOn(api,'billingRecords').mockResolvedValue(page([]))
  vi.spyOn(clipApi,'quote').mockResolvedValue(ok({ estimated_cost:'0.16',currency:'CNY',original_cost:'0.16',
    available_balance:null,shortfall:null,allowed:true,reason:'',note:'' }))
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.useRealTimers() })
async function render(start=false, billing=false) {
  const router = createRouter({history:createMemoryHistory(), routes:[{path:'/create/clip/:projectId',name:'clip-studio',component:{template:'<div/>'}},{path:'/',component:{template:'<div/>'}}]})
  await router.push('/create/clip/17' + (start ? '?start=1' : '')); await router.isReady()
  const pinia = createPinia()
  if (billing) useAuthStore(pinia).enabled = false
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
  expect(wrapper.text()).toContain('视频生成详情')
  expect(wrapper.text()).toContain('等待生成')
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
  expect(wrapper.get('.clip-media-result__stage').attributes('style')).toMatch(/aspect-ratio:\s*16\s*\/\s*9/)
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

it('does not reload the session when removing only the auto-start query', async () => {
  const {wrapper,router} = await render(true)
  expect(router.currentRoute.value.query.start).toBeUndefined()
  expect(clipApi.session).toHaveBeenCalledTimes(1)
  expect(wrapper.find('.studio-layout').exists()).toBe(true)
})

it('shows the workspace while result history is still loading', async () => {
  let resolveHistory!: (value: Awaited<ReturnType<typeof api.videoGenerationHistory>>) => void
  vi.mocked(api.videoGenerationHistory).mockImplementationOnce(() => new Promise(resolve => { resolveHistory = resolve }))
  const {wrapper} = await render()
  expect(wrapper.find('.studio-layout').exists()).toBe(true)
  expect(wrapper.find('[aria-label="创作助手"]').exists()).toBe(true)
  expect(wrapper.text()).toContain(session.name)
  resolveHistory(ok([]))
  await flushPromises()
})

it('shows a retry action after the session request times out', async () => {
  vi.mocked(clipApi.session).mockRejectedValueOnce(new DOMException('Timed out','TimeoutError'))
  const {wrapper} = await render()
  expect(wrapper.get('[role="alert"]').text()).toBe('片段读取超时，请重试')
  expect(wrapper.text()).not.toContain('正在恢复创作')
  await wrapper.findAll('button').find(button => button.text()==='重试')!.trigger('click')
  await flushPromises()
  expect(wrapper.find('.studio-layout').exists()).toBe(true)
  expect(clipApi.start).not.toHaveBeenCalled()
})

it('shows image generation details and correctly matches actual cost across billing pages', async () => {
  vi.useFakeTimers()
  vi.mocked(clipApi.session).mockResolvedValue(ok({ ...session, task_type:'image', asset_id:9, image_model_config_id:2, resolution:'2K' }))
  vi.mocked(api.assets).mockResolvedValue(page([{ id:9,novel_id:17,asset_type:2,canonical_name:'画面参考',main_image:'/media/result.png',base_traits:'竹林剑客',metadata:{resolution:'2K'},created_at:'',updated_at:'' } as Asset]))
  vi.mocked(api.assetGenerationHistory).mockResolvedValue(ok([{ id:'image-task', status:3, images:['/media/result.png'],
    clarity:'2K', aspect_ratio:'16:9', created_at:'2026-11-10T00:00:00Z', finished_at:'2026-11-10T00:00:29Z' } as AssetGenerationRecord]))
  const ledger = {id:1,novel_id:17,task_type:2,billing_type:'image',ai_task_id:'image-task',model:'gpt-image-2',
    cost:0.16,currency:'CNY',status:3,usage:{},created_at:'',updated_at:''} as BillingRecord
  vi.mocked(api.billingRecords).mockImplementation(async params => params?.page === 2 ? page([{...ledger,id:3,billing_type:'text',cost:0.02}])
    : { ...page([ledger,{...ledger,id:2,billing_type:'video',video_id:5,cost:2}]),data:{items:[ledger,{...ledger,id:2,billing_type:'video',video_id:5,cost:2}],pagination:{total:3,page:1,page_size:100,pages:2}} })
  const { wrapper } = await render(false, true)
  await vi.advanceTimersByTimeAsync(300)
  expect(wrapper.text()).toContain('图片生成详情')
  expect(wrapper.text()).not.toContain('把想法变成画面')
  expect(wrapper.get('.studio-cost-summary').text()).toContain('¥2.18')
  expect(wrapper.get('.clip-media-result__cost').text()).toBe('¥0.1600')
  expect(wrapper.get('time').text()).toBe('29 秒')
  expect(clipApi.quote).toHaveBeenCalledWith(expect.objectContaining({task_type:'image',model_config_id:2,resolution:'2K',mode:'direct'}),expect.any(AbortSignal))
  expect(api.billingRecords).toHaveBeenCalledWith({novel_id:17,page:2,page_size:100})
  expect(clipApi.start).not.toHaveBeenCalled()
})

it('keeps billing failures separate from successful generated media', async () => {
  vi.mocked(api.billingRecords).mockRejectedValue(new Error('billing unavailable'))
  vi.mocked(api.videoGenerationHistory).mockResolvedValue(ok([{ id:81,scene_id:30,status:3,url:'/media/result.mp4',metadata:{},created_at:'',updated_at:'' } as Video]))
  const { wrapper } = await render(false, true)
  expect(wrapper.find('video').exists()).toBe(true)
  expect(wrapper.get('.clip-media-result__cost').text()).toBe('费用暂未同步')
  expect(wrapper.find('.studio-error').exists()).toBe(false)
})

it('shows the image loading stage before the start request returns', async () => {
  let resolveStart!: (value: Awaited<ReturnType<typeof clipApi.start>>) => void
  vi.mocked(clipApi.start).mockImplementationOnce(() => new Promise(resolve => { resolveStart = resolve }))
  vi.mocked(clipApi.session).mockResolvedValue(ok({ ...session,task_type:'image',asset_id:9,image_model_config_id:2,resolution:'2K' }))
  vi.mocked(api.assets).mockResolvedValue(page([{id:9,novel_id:17,asset_type:2,canonical_name:'画面参考',base_traits:'已保存的提示词',metadata:{resolution:'2K'},created_at:'',updated_at:''} as Asset]))
  const { wrapper } = await render(true)
  expect(wrapper.get('.clip-media-result__stage').attributes('aria-busy')).toBe('true')
  expect(wrapper.text()).toContain('正在准备生成')
  expect(wrapper.findAll('button').find(button => button.text()==='生成图片')!.attributes('disabled')).toBeDefined()
  resolveStart(ok({task_id:'started',conversation_id:40,status:2} as AgentRun))
  await flushPromises()
  expect(clipApi.start).toHaveBeenCalledTimes(1)
})

it('prevents duplicate video submission while its real generation record is active', async () => {
  vi.mocked(api.videoGenerationHistory).mockResolvedValue(ok([{id:81,scene_id:30,status:2,created_at:new Date().toISOString(),updated_at:'',metadata:{}} as Video]))
  const { wrapper,store } = await render()
  const send = vi.spyOn(store,'send')
  expect(wrapper.get('.clip-media-result__stage').attributes('aria-busy')).toBe('true')
  const button = wrapper.findAll('button').find(item => item.text()==='生成视频')!
  expect(button.attributes('disabled')).toBeDefined()
  await button.trigger('click')
  expect(send).not.toHaveBeenCalled()
})
