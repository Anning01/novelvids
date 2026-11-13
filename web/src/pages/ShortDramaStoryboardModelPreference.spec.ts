import { createPinia } from 'pinia'
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

const modelCapabilities = {
  resolutions: ['720p'],
  default_resolution: '720p',
  aspect_ratios: ['9:16'],
  aspect_ratios_by_mode: { reference: ['9:16'] },
  default_aspect_ratio: '9:16',
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
      plugins: [router, createPinia()],
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
        { config_id: 11, name: '模型 A', capabilities: modelCapabilities },
        { config_id: 22, name: '模型 B', capabilities: modelCapabilities },
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

  it('按镜展示 MCP 已导入的各模型稿，即使本地没有相应的视频模型', async () => {
    vi.mocked(api.videoGenerationModels).mockResolvedValue({code: 0, message: 'ok', data: []})
    vi.mocked(api.workbenchBootstrap).mockResolvedValue({
      code: 0, message: 'ok', data: { chapter, assets: [], videos: {}, scenes: [
        {id: 4, sequence: 4, duration: 15, prompt: '门内听到喊声',
          metadata: {work_package: {drafts: {general: '门内听到喊声', minimax_h3: 'H3 喂水'}}}},
        {id: 5, sequence: 5, duration: 15, prompt: '递窝头',
          metadata: {work_package: {drafts: {general: '递窝头', seedance_2_5: 'Seedance 接窝头'}}}},
      ]},
    } as never)
    const wrapper = await mountPage()
    try {
      await flushPromises()
      const fourth = wrapper.get('[data-scene-id="4"] .model-optimized-prompt')
      const fifth = wrapper.get('[data-scene-id="5"] .model-optimized-prompt')
      expect(fourth.get('p').text()).toBe('H3 喂水')
      expect(fifth.get('p').text()).toBe('Seedance 接窝头')
      expect(fourth.find('button').exists()).toBe(false)
    } finally { wrapper.unmount() }
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
