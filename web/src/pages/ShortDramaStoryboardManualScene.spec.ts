import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ShortDramaStoryboardPage from './ShortDramaStoryboardPage.vue'
import AppButton from '@/components/AppButton.vue'
import { api } from '@/api'

vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      novelMeta: vi.fn(),
      chapters: vi.fn(),
      videoGenerationModels: vi.fn(),
      workbenchBootstrap: vi.fn(),
      novelAnalysis: vi.fn(),
      createChapter: vi.fn(),
      createScene: vi.fn(),
      scenes: vi.fn(),
      assets: vi.fn(),
      videos: vi.fn(),
      videoGenerationHistory: vi.fn(),
      generalConfig: vi.fn(),
      generationCapabilities: vi.fn(),
      imageGenerationModels: vi.fn(),
    },
  }
})

const chapter = {
  id: 1,
  novel_id: 9,
  number: 1,
  name: '第一章',
  content: '',
  created_at: '2026-08-18T00:00:00.000Z',
  updated_at: '2026-08-18T00:00:00.000Z',
}

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/create/short-drama/storyboard/:projectId', component: ShortDramaStoryboardPage }],
  })
  await router.push('/create/short-drama/storyboard/9')
  await router.isReady()
  return mount(ShortDramaStoryboardPage, {
    global: { plugins: [createPinia(), router], components: { AppButton } },
  })
}

describe('人工模式无章节时创建第一个分镜', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(api.novelMeta).mockResolvedValue({
      code: 0, message: 'ok',
      data: { id: 9, name: '新项目', author: '人工创建', description: '人工模式 · 9:16 · 720p · 写实通用', total_chapters: 0, content_length: 0, created_at: '', updated_at: '' },
    } as never)
    vi.mocked(api.chapters).mockResolvedValue({
      code: 0, message: 'ok',
      data: { items: [], pagination: { total: 0, page: 1, page_size: 100, pages: 0 } },
    } as never)
    vi.mocked(api.videoGenerationModels).mockResolvedValue({ code: 0, message: 'ok', data: [] } as never)
    vi.mocked(api.novelAnalysis).mockResolvedValue({ code: 0, message: 'ok', data: null } as never)
    vi.mocked(api.scenes).mockResolvedValue({ code: 0, message: 'ok', data: { items: [], pagination: { total: 0, page: 1, page_size: 100, pages: 0 } } } as never)
    vi.mocked(api.createChapter).mockResolvedValue({ code: 0, message: 'ok', data: chapter } as never)
    vi.mocked(api.createScene).mockResolvedValue({
      code: 0, message: 'ok',
      data: { id: 100, chapter_id: 1, sequence: 1, description: '', prompt: '', duration: 6, created_at: '', updated_at: '' },
    } as never)
  })

  it('无章节时点击「创建第一个分镜」自动建章并展示分镜操作框', async () => {
    const wrapper = await mountPage()
    await flushPromises()
    const button = wrapper.findAll('button').find(item => item.text().includes('创建第一个分镜'))
    expect(button).toBeTruthy()
    await button!.trigger('click')
    await flushPromises()
    expect(api.createChapter).toHaveBeenCalledWith(expect.objectContaining({ novel_id: 9, number: 1, name: '第一章' }))
    expect(api.createScene).toHaveBeenCalledWith(expect.objectContaining({ chapter_id: 1, sequence: 1 }))
    expect(wrapper.findAll('.shot-editor').length).toBeGreaterThan(0)
  })
})
