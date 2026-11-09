import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, expect, it, vi } from 'vitest'
import HomePage from './HomePage.vue'
import { applySavedLocale, beginLocaleChange, setLocale } from '@/i18n'
import { api } from '@/api'
import { clipApi } from '@/features/creation-agent/clipApi'
import type { ClipSession } from '@/features/creation-agent/clipApi'
import type { VideoGenerationModel, ImageGenerationModel } from '@/types'

const ok = <T,>(data: T) => ({ code: 0, message: 'ok', data })
const video = { config_id: 22, name: '团队视频模型', capabilities: { aspect_ratios: ['16:9', '9:16'], resolutions: ['720p', '1080p'], duration_min: 5, duration_max: 10, default_aspect_ratio: '16:9' } } as VideoGenerationModel
const image = { config_id: 31, name: '团队图片模型', capabilities: { aspect_ratios: ['1:1', '16:9'], clarities: ['2K'], default_aspect_ratio: '1:1' } } as ImageGenerationModel
const select = { props: ['modelValue', 'options', 'ariaLabel', 'disabled'], emits: ['update:modelValue'], template: `<select :aria-label="ariaLabel" :value="modelValue" :disabled="disabled" @change="$emit('update:modelValue', $event.target.value)"><option v-for="option in options" :key="typeof option === 'string' ? option : option.value" :value="typeof option === 'string' ? option : option.value">{{ typeof option === 'string' ? option : option.label }}</option></select>` }

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'videoGenerationModels').mockResolvedValue(ok([video]))
  vi.spyOn(api, 'imageGenerationModels').mockResolvedValue(ok([image]))
  vi.spyOn(api, 'experienceShowcase').mockResolvedValue(ok([]))
  vi.spyOn(clipApi, 'recent').mockResolvedValue(ok([]))
  vi.spyOn(clipApi, 'quote').mockResolvedValue(ok({estimated_cost:'0.5',available_balance:'10',shortfall:'0',currency:'CNY',allowed:true,reason:'',note:'按实际用量结算'}))
})
async function settleQuote() { await new Promise(resolve => setTimeout(resolve, 275)); await flushPromises() }
async function render() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', component: {template:'<div />'} },
    { path: '/create/clip/:projectId', name: 'clip-studio', component: {template:'<div />'} },
  ] })
  await router.push('/'); await router.isReady()
  const wrapper = mount(HomePage, { global: { plugins: [createPinia(), router], stubs: { AppSelect: select, ClipReferencePrompt: {props:['modelValue','references'],emits:['update:modelValue','remove'],template:'<div><textarea id="clip-idea" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" /></div>'} } } })
  await flushPromises()
  await settleQuote()
  return {wrapper, router}
}
it('uses configured models, real empty works, and keeps series in My Creation', async () => {
  const {wrapper} = await render()
  expect(wrapper.text()).toContain('具现想象')
  expect(wrapper.findAll('.home-shortcuts > a')).toHaveLength(4)
  expect(wrapper.text()).toContain('团队视频模型')
  expect(wrapper.text()).toContain('还没有公开作品')
  expect(wrapper.get('a[href="/projects"]').text()).toContain('我的创作')
  expect(wrapper.text()).not.toContain('42.8w')
  expect(wrapper.text()).not.toContain('Wan 3.0')
  expect(wrapper.get('[aria-label="开始创作"]').attributes('disabled')).toBeDefined()
})

it.each(['light', 'dark'])('renders the English home, categories and quote warnings without rewriting user content (%s)', async theme => {
  document.documentElement.dataset.appTheme = theme
  setLocale('en')
  vi.mocked(clipApi.quote).mockResolvedValue(ok({ estimated_cost: '0.5', available_balance: null, shortfall: null,
    currency: 'CNY', allowed: false, reason: '请先切换到要创建作品的团队', note: '' }))
  const work = { id: 'work-1', title: '保留原作标题', cover: '', video_url: '', episodes_count: 1, duration: '00:05',
    category: '写实通用', tags: [], heat: '', description: '创作者的原文说明', author: '作者原名', novel_id: 1 }
  vi.mocked(api.experienceShowcase).mockResolvedValue(ok([work, { ...work, id: 'work-2', category: '3D仙侠', novel_id: 2 }]))
  const { wrapper } = await render()
  expect(wrapper.get('.home-heading').text()).toContain('Imagine it')
  expect(wrapper.get('.home-heading').text()).not.toMatch(/[\u4e00-\u9fff]/)
  for (const selector of ['.composer-tabs', '.models-label', '.inspiration-list', '.upload-reference', '.composer-settings', '.composer-actions', '.home-shortcuts', '.gallery-heading', '.showcase-filters', '.composer-quote-warning']) {
    expect(wrapper.get(selector).text(), selector).not.toMatch(/[\u4e00-\u9fff]/)
  }
  expect(wrapper.get('.showcase-filters').text()).toContain('General realism')
  expect(wrapper.get('.showcase-filters').text()).toContain('3D xianxia')
  expect(wrapper.get('.composer-quote-warning').text()).toContain('Switch to the team you want to create in first')
  expect(wrapper.get('.work-title').text()).toBe(work.title)
  expect(wrapper.get('.work-description').text()).toBe(work.description)
  await wrapper.get('#clip-idea').setValue('保留我的提示词 @{图片1}')
  setLocale('zh')
  await flushPromises()
  expect(wrapper.get('.home-heading').text()).toContain('具现想象')
  expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('保留我的提示词 @{图片1}')
  wrapper.unmount()
  delete document.documentElement.dataset.appTheme
})

it('uses the current language for inspiration only when the user chooses it', async () => {
  const { wrapper } = await render()
  await wrapper.findAll('.inspiration-list button')[0]!.trigger('click')
  const chineseDraft = (wrapper.get('textarea').element as HTMLTextAreaElement).value
  setLocale('en')
  await flushPromises()
  expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe(chineseDraft)
  expect(wrapper.findAll('.inspiration-list button')[0]!.text()).toBe('Rainy pursuit')
  await wrapper.findAll('.inspiration-list button')[0]!.trigger('click')
  const englishDraft = (wrapper.get('textarea').element as HTMLTextAreaElement).value
  expect(englishDraft).toContain('On a rainy street at night')
  expect(englishDraft).not.toMatch(/[\u4e00-\u9fff]/)
  setLocale('zh')
  await flushPromises()
  expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe(englishDraft)
})

it('updates already displayed load errors when the language changes', async () => {
  vi.mocked(api.videoGenerationModels).mockRejectedValue(new Error('unavailable'))
  vi.mocked(api.experienceShowcase).mockRejectedValue(new Error('unavailable'))
  const { wrapper } = await render()
  expect(wrapper.get('.home-error').text()).toContain('部分创作配置未能加载')
  setLocale('en')
  await flushPromises()
  expect(wrapper.get('.home-error').text()).toContain('Some creation settings could not load')
  expect(wrapper.get('.gallery-state').text()).toContain('Works are temporarily unavailable')
  setLocale('zh')
  await flushPromises()
  expect(wrapper.get('.home-error').text()).toContain('部分创作配置未能加载')
  expect(api.videoGenerationModels).toHaveBeenCalledOnce()
})

it('waits for language persistence before refreshing quote messages or starting a creation', async () => {
  const { wrapper } = await render()
  await wrapper.get('#clip-idea').setValue('Keep this draft')
  const previousRequests = vi.mocked(clipApi.quote).mock.calls.length
  beginLocaleChange('en')
  await settleQuote()
  expect(clipApi.quote).toHaveBeenCalledTimes(previousRequests)
  expect(wrapper.get('.generate-action-btn').attributes('disabled')).toBeDefined()
  expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('Keep this draft')
  applySavedLocale('en')
  await settleQuote()
  expect(clipApi.quote).toHaveBeenCalledTimes(previousRequests + 1)
  expect(wrapper.get('.generate-action-btn').attributes('disabled')).toBeUndefined()
})
it('switches model capabilities and sends selected settings to the real clip API', async () => {
  vi.spyOn(clipApi, 'create').mockResolvedValue(ok({project_id: 90} as ClipSession))
  const {wrapper, router} = await render()
  await wrapper.get('#clip-idea').setValue('我的完整提示词')
  await wrapper.get('select[aria-label="创作方式"]').setValue('direct')
  await wrapper.get('select[aria-label="画面比例"]').setValue('9:16')
  await wrapper.get('select[aria-label="清晰度"]').setValue('1080p')
  await wrapper.get('select[aria-label="片段时长"]').setValue('8')
  await settleQuote()
  await wrapper.get('[aria-label="立即生成"]').trigger('click')
  await flushPromises()
  expect(clipApi.create).toHaveBeenCalledWith(expect.objectContaining({prompt:'我的完整提示词', mode:'direct', model_config_id:22, aspect_ratio:'9:16', resolution:'1080p', duration:8}))
  expect(router.currentRoute.value.fullPath).toBe('/create/clip/90?start=1')
  expect(wrapper.find('.showcase-section').exists()).toBe(false)
  expect(wrapper.find('.home-shortcuts').exists()).toBe(false)
})
it('retains input and reuses the request ID after an uncertain creation failure', async () => {
  const create = vi.spyOn(clipApi, 'create').mockRejectedValue(new Error('连接中断'))
  const {wrapper} = await render()
  await wrapper.get('#clip-idea').setValue('保留这个想法')
  await wrapper.get('[aria-label="开始创作"]').trigger('click'); await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('连接中断')
  expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('保留这个想法')
  await wrapper.get('[aria-label="开始创作"]').trigger('click'); await flushPromises()
  expect(create.mock.calls[0]?.[0].request_id).toBe(create.mock.calls[1]?.[0].request_id)
})
it('supports real image capabilities and reference image upload', async () => {
  const {wrapper} = await render()
  await wrapper.get('select[aria-label="画面比例"]').setValue('9:16')
  await wrapper.findAll('.composer-tabs button')[1]!.trigger('click'); await flushPromises()
  expect(wrapper.text()).toContain('团队图片模型')
  expect(wrapper.find('[aria-label="片段时长"]').exists()).toBe(false)
  expect(wrapper.find('[aria-label="上传参考素材"]').exists()).toBe(true)
  expect(wrapper.find('input[type="file"]').attributes('accept')).toBe('image/*')
  expect(wrapper.text()).not.toContain('先做参考图')
  expect((wrapper.get('select[aria-label="画面比例"]').element as HTMLSelectElement).value).toBe('1:1')
})
it('shows unavailable models and load failures instead of demo success', async () => {
  vi.mocked(api.videoGenerationModels).mockRejectedValue(new Error('unavailable'))
  const {wrapper} = await render()
  await wrapper.get('#clip-idea').setValue('一个想法')
  expect(wrapper.text()).toContain('暂未配置可用模型')
  expect(wrapper.get('[aria-label="开始创作"]').attributes('disabled')).toBeDefined()
  expect(wrapper.get('[role="alert"]').text()).toContain('未能加载')
})


it('uses inspiration only as editable input without submitting a generation', async () => {
  const create = vi.spyOn(clipApi, 'create')
  const {wrapper} = await render()
  await wrapper.findAll('.inspiration-list button')[0]!.trigger('click')
  expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toContain('雨夜街头')
  expect(create).not.toHaveBeenCalled()
  expect(wrapper.get('[aria-label="开始创作"]').attributes('disabled')).toBeUndefined()
})

it('shows real work details, filters real categories and preserves native cover proportions', async () => {
  const work = {id:'work-1',title:'真实作品',cover:'/media/cover.jpg',video_url:'',episodes_count:1,duration:'01:12',category:'悬疑',tags:['悬疑'],heat:'',description:'雨夜发生的一次重逢。',author:'创作者',novel_id:13}
  vi.mocked(api.experienceShowcase).mockResolvedValue(ok([work,{...work,id:'work-2',title:'另一部作品',category:'古风',novel_id:14}]))
  const {wrapper} = await render()
  expect(wrapper.findAll('.showcase-card')).toHaveLength(2)
  await wrapper.findAll('.showcase-filters button').find(button=>button.text()==='悬疑')!.trigger('click')
  expect(wrapper.findAll('.showcase-card')).toHaveLength(1)
  expect(wrapper.find('.showcase-masonry').exists()).toBe(true)
  expect(wrapper.find('.is-single').exists()).toBe(false)
  expect(wrapper.get('.work-description').text()).toBe(work.description)
  expect(wrapper.get('.work-duration').text()).toBe('01:12')
  const image = wrapper.get('.work-visual img')
  Object.defineProperties(image.element,{naturalWidth:{value:1920},naturalHeight:{value:1080}})
  await image.trigger('load')
  expect(wrapper.get('.work-visual').attributes('style')).toContain('1920')
  expect(wrapper.get('.showcase-card').attributes('aria-haspopup')).toBe('dialog')
  expect(wrapper.text()).not.toContain('热度')
})

it('keeps decorative GIFs looping without a pause control', async () => {
  const {wrapper} = await render()
  const pictures = wrapper.findAll('.shortcut-art')
  expect(pictures).toHaveLength(2)
  expect(pictures.map(picture => picture.get('img').attributes('src'))).toEqual([
    '/home-art/cloud-palace-v1.gif', '/home-art/rain-street-v1.gif',
  ])
  expect(wrapper.find('.shortcut-heading button').exists()).toBe(false)
  expect(wrapper.text()).not.toContain('暂停动效')
  expect(wrapper.text()).not.toContain('播放动效')
})

it('keeps multiple named uploads and submits explicit mention binding', async () => {
  vi.spyOn(api,'uploadVideoReference').mockResolvedValueOnce({type:'image',url:'/media/one.png',name:'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg'})
    .mockResolvedValueOnce({type:'image',url:'/media/two.png',name:'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.jpg'})
  vi.spyOn(clipApi,'create').mockResolvedValue(ok({project_id:90} as ClipSession))
  const {wrapper}=await render()
  const picker=wrapper.get('input[type="file"]')
  Object.defineProperty(picker.element,'files',{configurable:true,value:[new File(['one'],'one.png',{type:'image/png'}),new File(['two'],'two.png',{type:'image/png'})]})
  await picker.trigger('change');await flushPromises()
  await wrapper.get('#clip-idea').setValue('按 @{图片2} 生成镜头。')
  await settleQuote()
  await wrapper.get('[aria-label="开始创作"]').trigger('click');await flushPromises()
  expect(clipApi.create).toHaveBeenCalledWith(expect.objectContaining({prompt:'按 @{图片2} 生成镜头。',reference_binding:'mentions',reference_media:[expect.objectContaining({mention_name:'图片1'}),expect.objectContaining({mention_name:'图片2'})]}))
})


it('shows the estimate and blocks a positive balance below the estimated cost', async () => {
  vi.mocked(clipApi.quote).mockResolvedValue(ok({estimated_cost:'0.5',available_balance:'0.49',shortfall:'0.01',currency:'CNY',allowed:false,reason:'团队余额不足，请先充值',note:''}))
  const create=vi.spyOn(clipApi,'create')
  const {wrapper}=await render()
  await wrapper.get('#clip-idea').setValue('雨夜街头')
  expect(wrapper.get('.generate-btn-discount').text()).toBe('¥0.50')
  expect(wrapper.get('.composer-quote').text()).toContain('还差 ¥0.01')
  expect(wrapper.get('[aria-label="开始创作"]').attributes('disabled')).toBeDefined()
  expect(create).not.toHaveBeenCalled()
})

it('invalidates the old estimate immediately when parameters change',async()=>{
  const {wrapper}=await render()
  await wrapper.get('#clip-idea').setValue('雨夜街头')
  expect(wrapper.get('[aria-label="开始创作"]').attributes('disabled')).toBeUndefined()
  vi.mocked(clipApi.quote).mockResolvedValue(ok({estimated_cost:'1',available_balance:'0.5',shortfall:'0.5',currency:'CNY',allowed:false,reason:'团队余额不足，请先充值',note:''}))
  await wrapper.get('select[aria-label="片段时长"]').setValue('10')
  expect(wrapper.get('[aria-label="开始创作"]').attributes('disabled')).toBeDefined()
  await settleQuote()
  expect(wrapper.get('.generate-btn-discount').text()).toBe('¥1.00')
})

it('rechecks funds before navigation and never proceeds with an unavailable quote',async()=>{
  const {wrapper,router}=await render()
  const create=vi.spyOn(clipApi,'create')
  await wrapper.get('#clip-idea').setValue('雨夜街头')
  vi.mocked(clipApi.quote).mockResolvedValue(ok({estimated_cost:'0.5',available_balance:'0',shortfall:'0.5',currency:'CNY',allowed:false,reason:'团队余额不足，请先充值',note:''}))
  await wrapper.get('[aria-label="开始创作"]').trigger('click');await flushPromises()
  expect(create).not.toHaveBeenCalled()
  expect(router.currentRoute.value.path).toBe('/')
  expect(wrapper.find('.entry-state').exists()).toBe(false)
})

it('ignores an older response after a newer quote has blocked generation',async()=>{
  let resolveFirst!: (value: Awaited<ReturnType<typeof clipApi.quote>>) => void
  vi.mocked(clipApi.quote).mockImplementationOnce(() => new Promise(resolve => {resolveFirst=resolve}))
  const {wrapper}=await render()
  await wrapper.get('#clip-idea').setValue('雨夜街头')
  vi.mocked(clipApi.quote).mockResolvedValue(ok({estimated_cost:'1',available_balance:'0.5',shortfall:'0.5',currency:'CNY',allowed:false,reason:'余额不足',note:''}))
  await wrapper.get('select[aria-label="片段时长"]').setValue('10')
  await settleQuote()
  resolveFirst(ok({estimated_cost:'0.1',available_balance:'10',shortfall:'0',currency:'CNY',allowed:true,reason:'',note:''}))
  await flushPromises()
  expect(wrapper.get('[aria-label="开始创作"]').attributes('disabled')).toBeDefined()
  expect(wrapper.get('.generate-btn-discount').text()).toBe('¥1.00')
  expect(wrapper.get('.generate-btn-discount').text()).not.toBe('¥0.10')
})

it('displays the action button with estimated prices, strikethrough original price and discount badge', async () => {
  vi.mocked(clipApi.quote).mockResolvedValue(ok({
    estimated_cost: '2.38',
    original_cost: '5.96',
    discount: '0.4',
    discount_description: '限时4折',
    available_balance: '989.087584',
    shortfall: '0',
    currency: 'CNY',
    allowed: true,
    reason: '',
    note: '图片/视频按当前参数估算，助手费用按实际用量另计。',
  }))
  const {wrapper} = await render()
  const btn = wrapper.get('.generate-action-btn')
  expect(btn.text()).toContain('生成')
  expect(btn.text()).toContain('约')
  expect(btn.get('.generate-btn-original').text()).toBe('¥5.96')
  expect(btn.get('.generate-btn-discount').text()).toBe('¥2.38')
  expect(btn.find('.discount-badge-svg').exists()).toBe(true)
  expect(wrapper.find('.composer-estimation').exists()).toBe(false)
  expect(wrapper.text()).not.toContain('预计生成费用')
  expect(wrapper.text()).not.toContain('可用余额')
})
