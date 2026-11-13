import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
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

async function selectInput(wrapper: VueWrapper, label: string) {
  await wrapper.get('.source-kind-switch').findAll('button').find(button => button.text() === label)!.trigger('click')
  await flushPromises()
}

it('selects a backend strategy on project creation and persists it', async () => {
  const wrapper = mount(ShortDramaPage, {
    global: { components: { AppButton } },
  })
  await flushPromises()

  expect(wrapper.get('button[aria-label="画面比例"]').text()).toContain('16:9')
  const strategyTrigger = wrapper.get('button[aria-label="分镜策略"]')
  expect(strategyTrigger.text()).toContain('电影感叙事')
  await strategyTrigger.trigger('click')
  await flushPromises()
  const narrationOption = document.body.querySelectorAll<HTMLElement>('[role="option"]')
  const target = [...narrationOption].find(option => option.textContent?.includes('旁白叙事'))
  expect(target).toBeTruthy()
  target?.click()
  await flushPromises()

  await selectInput(wrapper, '现成剧本')
  await wrapper.findAll('button').find(button => button.text().includes('粘贴正文'))!.trigger('click')
  await wrapper.get('#story-content').setValue('1-1 客厅 内 日，林夏进门。')
  await wrapper.get('#story-title').setValue('新项目')
  await wrapper.get('form').trigger('submit')
  await flushPromises()

  expect(api.createNovel).toHaveBeenCalledWith(expect.objectContaining({
    storyboard_strategy: 'narration',
    storyboard_setting: '旁白规则',
    name: '新项目',
    content: '1-1 客厅 内 日，林夏进门。',
    aspect_ratio: '16:9',
    resolution: '720p',
    style_key: 'realistic-general',
    custom_style_prompt: null,
  }))
  expect(api.splitNovel).not.toHaveBeenCalled()
  expect(push).toHaveBeenCalledWith({name: 'short-drama-agent', params: {projectId: 19}})
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


it.each(['light', 'dark'])('imports a screenplay directly with an empty original in %s mode', async (theme) => {
  document.documentElement.dataset.appTheme = theme
  vi.mocked(api.createNovel).mockResolvedValue({
    code: 0, message: '', data: { id: 19, name: '现成剧本', content: '', total_chapters: 2, episodes_managed: true, created_at: '', updated_at: '' },
  })
  const wrapper = mount(ShortDramaPage, { global: { components: { AppButton } } })
  await flushPromises()
  await selectInput(wrapper, '现成剧本')
  const scriptButton = wrapper.get('.source-kind-switch').findAll('button').find(button => button.text() === '现成剧本')!
  expect(scriptButton.text()).toContain('现成剧本')
  await wrapper.findAll('button').find(button => button.text().includes('粘贴正文'))!.trigger('click')
  const content = '第一集 雨夜\n1-1 车站 外 夜\n△ 林夏撑伞。\n第二集 清晨\n2-1 家 内 日\n林夏：回来了。'
  await wrapper.get('#story-content').setValue(content)
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(api.createNovel).toHaveBeenCalledWith(expect.objectContaining({ source_kind: 'screenplay', content }))
  expect(api.splitNovel).not.toHaveBeenCalled()
  expect(push).toHaveBeenCalledWith({ name: 'short-drama-agent', params: { projectId: 19 } })
  wrapper.unmount()
  delete document.documentElement.dataset.appTheme
})


it('retains screenplay input after failure and disables content selection during import', async () => {
  let rejectCreate!: (error: Error) => void
  vi.mocked(api.createNovel).mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectCreate = reject }))
  const wrapper = mount(ShortDramaPage, { global: { components: { AppButton } } })
  await flushPromises()
  await selectInput(wrapper, '现成剧本')
  const scriptButton = wrapper.get('.source-kind-switch').findAll('button').find(button => button.text() === '现成剧本')!
  await wrapper.findAll('button').find(button => button.text().includes('粘贴正文'))!.trigger('click')
  const content = '1-1 客厅 内 日\n林夏：你好。'
  await wrapper.get('#story-content').setValue(content)
  await wrapper.get('form').trigger('submit')
  expect(scriptButton.attributes('disabled')).toBeDefined()
  expect(wrapper.get('#story-content').attributes('disabled')).toBeDefined()
  rejectCreate(new Error('保存失败'))
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('保存失败')
  expect(wrapper.get<HTMLTextAreaElement>('#story-content').element.value).toBe(content)
  expect(scriptButton.text()).toContain('现成剧本')
  expect(scriptButton.attributes('disabled')).toBeUndefined()
  expect(api.splitNovel).not.toHaveBeenCalled()
  wrapper.unmount()
})


it('keeps a two-option switch in the settings bar and preserves text when switching', async () => {
  const wrapper = mount(ShortDramaPage)
  await flushPromises()
  expect(wrapper.get('.creation-config-bar .source-kind-switch').findAll('button')).toHaveLength(2)
  expect(wrapper.text()).not.toContain('输入内容')
  expect(wrapper.text()).not.toContain('空白创建')
  await wrapper.get('#story-title').setValue('保留名称')
  await wrapper.findAll('button').find(button => button.text().includes('粘贴正文'))!.trigger('click')
  await wrapper.get('#story-content').setValue('林夏推门。')
  await selectInput(wrapper, '现成剧本')
  expect(wrapper.get<HTMLTextAreaElement>('#story-content').element.value).toBe('林夏推门。')
  await selectInput(wrapper, '小说原文')
  expect(wrapper.get<HTMLTextAreaElement>('#story-content').element.value).toBe('林夏推门。')
  expect(wrapper.get<HTMLInputElement>('#story-title').element.value).toBe('保留名称')
  wrapper.unmount()
})

it('reopens a saved screenplay after navigation fails without creating or splitting again', async () => {
  push.mockRejectedValueOnce(new Error('跳转失败')).mockResolvedValueOnce(undefined)
  const wrapper = mount(ShortDramaPage)
  await flushPromises()
  await selectInput(wrapper, '现成剧本')
  await wrapper.findAll('button').find(button => button.text().includes('粘贴正文'))!.trigger('click')
  await wrapper.get('#story-content').setValue('林夏推门。')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.get('.create-short-drama').text()).toContain('继续进入项目')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(api.createNovel).toHaveBeenCalledOnce()
  expect(api.splitNovel).not.toHaveBeenCalled()
  expect(api.chaptersPage).not.toHaveBeenCalled()
  wrapper.unmount()
})


it.each(['小说原文', '现成剧本'])('uploads a file as %s and retains its file and title across source types', async (label) => {
  vi.mocked(api.upload).mockResolvedValue({
    key: 'uploads/story.md', filename: '文件原名.md', file_path: '/media/story.md',
  } as Awaited<ReturnType<typeof api.upload>>)
  vi.mocked(api.splitNovel).mockResolvedValue({data: {total_chapters: 1}} as Awaited<ReturnType<typeof api.splitNovel>>)
  const wrapper = mount(ShortDramaPage)
  await flushPromises()
  await selectInput(wrapper, label)
  await wrapper.get('#story-title').setValue('用户指定名称')
  const file = new File(['1-1 客厅 内 日'], '文件原名.md', { type: 'text/markdown' })
  Object.defineProperty(wrapper.get('input[type="file"]').element, 'files', { value: [file] })
  await wrapper.get('input[type="file"]').trigger('change')
  await selectInput(wrapper, label === '小说原文' ? '现成剧本' : '小说原文')
  await selectInput(wrapper, label)
  expect(wrapper.text()).toContain('文件原名.md')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(api.upload).toHaveBeenCalledWith(file)
  expect(api.createNovel).toHaveBeenCalledWith(expect.objectContaining({
    name: '用户指定名称', source_kind: label === '小说原文' ? 'novel' : 'screenplay',
    source_key: 'uploads/story.md', source_filename: '文件原名.md',
  }))
  expect(api.splitNovel).toHaveBeenCalledTimes(label === '小说原文' ? 1 : 0)
  wrapper.unmount()
})
