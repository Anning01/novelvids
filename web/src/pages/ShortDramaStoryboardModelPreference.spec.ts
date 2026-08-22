import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
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
      updateNovel: vi.fn(),
      novelAnalysis: vi.fn(),
    },
  }
})

const chapter = {
  id: 337,
  novel_id: 7,
  number: 1,
  name: '第一章',
  content: '章节内容',
  created_at: '',
  updated_at: '',
}

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/create/short-drama/storyboard/:projectId', component: ShortDramaStoryboardPage }],
  })
  await router.push('/create/short-drama/storyboard/7?chapter=337')
  await router.isReady()
  return mount(ShortDramaStoryboardPage, {
    global: {
      plugins: [router],
      components: { AppButton },
      stubs: {
        Teleport: true,
        ShortDramaWorkspaceShell: { template: '<div><slot name="header-end" /><slot /></div>' },
      },
    },
  })
}

describe('分镜页面视频模型偏好', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    vi.mocked(api.novelMeta).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: {
        id: 7,
        name: '雾城',
        author: 'Agent 创建',
        description: 'Agent 模式 · 9:16 · 720p · 写实通用',
        total_chapters: 1,
        content_length: 10,
        video_model_config_id: 22,
        created_at: '',
        updated_at: '',
      },
    })
    vi.mocked(api.chapters).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { items: [chapter], pagination: { total: 1, page: 1, page_size: 100, pages: 1 } },
    } as never)
    vi.mocked(api.videoGenerationModels).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: [
        { config_id: 11, name: '模型 A' },
        { config_id: 22, name: '模型 B' },
      ],
    } as never)
    vi.mocked(api.workbenchBootstrap).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { chapter, assets: [], scenes: [], videos: {} },
    } as never)
    vi.mocked(api.updateNovel).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { id: 7, name: '雾城', video_model_config_id: 11, created_at: '', updated_at: '' },
    } as never)
  })

  it('刷新后恢复已保存模型，并在切换时立即落库', async () => {
    const wrapper = await mountPage()
    await flushPromises()

    const trigger = wrapper.get('button[aria-label="视频模型"]')
    expect(trigger.text()).toContain('模型 B')
    expect(api.updateNovel).not.toHaveBeenCalled()

    await trigger.trigger('click')
    const modelA = wrapper.findAll('[role="option"]').find(option => option.text().includes('模型 A'))
    expect(modelA).toBeTruthy()
    await modelA!.trigger('click')
    await flushPromises()

    expect(api.updateNovel).toHaveBeenCalledWith(7, { video_model_config_id: 11 })
    expect(trigger.text()).toContain('模型 A')
  })
})
