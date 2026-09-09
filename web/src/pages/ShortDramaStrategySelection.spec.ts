import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import AppButton from '@/components/AppButton.vue'
import ShortDramaPage from './ShortDramaPage.vue'

const push = vi.fn()

vi.mock('vue-router', () => ({
  useRouter: () => ({ push }),
}))

vi.mock('@/api', () => ({
  api: {
    visualStyles: vi.fn(),
    storyboardStrategies: vi.fn(),
    createNovel: vi.fn(),
    splitNovel: vi.fn(),
    chaptersPage: vi.fn(),
    deleteNovel: vi.fn(),
    upload: vi.fn(),
  },
}))

beforeEach(() => {
  vi.clearAllMocks()
  push.mockReset()
  sessionStorage.clear()
  vi.mocked(api.visualStyles).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: [{ key: 'realistic-general', label: '写实通用' }],
  })
  vi.mocked(api.storyboardStrategies).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: [
      { key: 'cinematic', name: '电影感叙事', description: '原电影感规则', is_default: true },
      { key: 'narration', name: '旁白叙事', description: '旁白规则', is_default: false },
    ],
  })
  vi.mocked(api.createNovel).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: {
      id: 19,
      name: '新项目',
      storyboard_strategy: 'narration',
      storyboard_setting: '旁白规则',
      created_at: '',
      updated_at: '',
    },
  })
})

it('selects a backend strategy on project creation and persists it', async () => {
  const wrapper = mount(ShortDramaPage, {
    global: { components: { AppButton } },
  })
  await flushPromises()

  const strategyTrigger = wrapper.get('button[aria-label="分镜策略"]')
  expect(strategyTrigger.text()).toContain('电影感叙事')
  await strategyTrigger.trigger('click')
  await flushPromises()
  const narrationOption = document.body.querySelectorAll<HTMLElement>('[role="option"]')
  const target = [...narrationOption].find(option => option.textContent?.includes('旁白叙事'))
  expect(target).toBeTruthy()
  target?.click()
  await flushPromises()

  const manualButton = wrapper.findAll('button').find(button => button.text().includes('人工模式'))
  expect(manualButton).toBeTruthy()
  await manualButton?.trigger('click')
  await wrapper.get('form').trigger('submit')
  await flushPromises()

  expect(api.createNovel).toHaveBeenCalledWith(expect.objectContaining({
    storyboard_strategy: 'narration',
    storyboard_setting: '旁白规则',
    description: '人工模式',
    aspect_ratio: '9:16',
    resolution: '720p',
    style_key: 'realistic-general',
    custom_style_prompt: null,
  }))
})


it('creates a chapter-based project from pasted prose using the existing import pipeline', async () => {
  vi.mocked(api.splitNovel).mockResolvedValue({ code: 0, message: '', data: { id: 19, name: '雨夜来信', total_chapters: 2, created_at: '', updated_at: '' } })
  const wrapper = mount(ShortDramaPage, { global: { components: { AppButton } } })
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text().includes('粘贴正文'))!.trigger('click')
  await wrapper.get('#story-title').setValue('雨夜来信')
  const content = '第一章 雨夜车站\n林夏穿灰色风衣，拿着一封信。\n第二章 清晨\n林夏走进咖啡馆。'
  await wrapper.get('#story-content').setValue(content)
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(api.upload).not.toHaveBeenCalled()
  expect(api.createNovel).toHaveBeenCalledWith(expect.objectContaining({ name: '雨夜来信', content, author: 'Agent 创建' }))
  expect(api.splitNovel).toHaveBeenCalledWith(19)
  expect(push).toHaveBeenCalledWith({ name: 'short-drama-agent', params: { projectId: 19 } })
  wrapper.unmount()
})

it('retains pasted text after a failed create and prevents duplicate in-flight submissions', async () => {
  let rejectCreate!: (error: Error) => void
  vi.mocked(api.createNovel).mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectCreate = reject }))
  const wrapper = mount(ShortDramaPage, { global: { components: { AppButton } } })
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text().includes('粘贴正文'))!.trigger('click')
  await wrapper.get('#story-content').setValue('第一章 雨夜车站，林夏等待来信。')
  await wrapper.get('form').trigger('submit')
  await wrapper.get('form').trigger('submit')
  expect(api.createNovel).toHaveBeenCalledOnce()
  rejectCreate(new Error('服务暂不可用'))
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('服务暂不可用')
  expect(wrapper.get<HTMLTextAreaElement>('#story-content').element.value).toContain('林夏等待来信')
  expect(push).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('resumes chapter recognition on the saved project after a network failure', async () => {
  vi.mocked(api.splitNovel).mockRejectedValueOnce(new Error('章节识别连接中断')).mockResolvedValueOnce({ data: { total_chapters: 2 } } as never)
  vi.mocked(api.chaptersPage).mockResolvedValue({ data: { items: [], pagination: { total: 0 } } } as never)
  const wrapper = mount(ShortDramaPage, { global: { components: { AppButton } } })
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text().includes('粘贴正文'))!.trigger('click')
  await wrapper.get('#story-content').setValue('第一章 雨夜\n林夏等待。')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(api.deleteNovel).not.toHaveBeenCalled()
  expect(wrapper.text()).toContain('继续识别章节')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(api.createNovel).toHaveBeenCalledOnce()
  expect(api.splitNovel).toHaveBeenNthCalledWith(2, 19)
  expect(push).toHaveBeenCalledWith({ name: 'short-drama-agent', params: { projectId: 19 } })
  wrapper.unmount()
})
