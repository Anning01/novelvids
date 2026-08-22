import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import ShortDramaVideoPage from './ShortDramaVideoPage.vue'
import { api } from '@/api'
import { downloadFile } from '@/shared/downloadFile'
import { TaskStatusEnum } from '@/types'

vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      novelMeta: vi.fn(),
      chapters: vi.fn(),
      workbenchBootstrap: vi.fn(),
      mergeChapterVideos: vi.fn(),
    },
  }
})

vi.mock('@/shared/downloadFile', () => ({ downloadFile: vi.fn() }))

const chapter = {
  id: 337,
  novel_id: 7,
  number: 12,
  name: '山雨欲来',
  created_at: '',
  updated_at: '',
}

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/create/short-drama/video/:projectId', component: ShortDramaVideoPage }],
  })
  await router.push('/create/short-drama/video/7?chapter=337')
  await router.isReady()
  return mount(ShortDramaVideoPage, {
    global: {
      plugins: [router],
      stubs: {
        ShortDramaWorkspaceShell: {
          template: '<div><slot name="header-end" /><slot /></div>',
        },
      },
    },
  })
}

describe('短剧视频页完整视频下载', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.novelMeta).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { id: 7, name: '雾城', author: '', description: '', content_length: 0, created_at: '', updated_at: '' },
    } as never)
    vi.mocked(api.chapters).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { items: [chapter], pagination: { total: 1, page: 1, page_size: 100, pages: 1 } },
    } as never)
    vi.mocked(api.workbenchBootstrap).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: {
        chapter,
        assets: [],
        scenes: [
          { id: 31, chapter_id: 337, sequence: 2, duration: 5, created_at: '', updated_at: '' },
          { id: 30, chapter_id: 337, sequence: 1, duration: 4, created_at: '', updated_at: '' },
          { id: 32, chapter_id: 337, sequence: 3, duration: 6, created_at: '', updated_at: '' },
        ],
        videos: {
          30: [{ id: 100, scene_id: 30, model_type: 1, status: TaskStatusEnum.COMPLETED, url: '/media/videos/100.mp4', created_at: '', updated_at: '' }],
          31: [{ id: 101, scene_id: 31, model_type: 1, status: TaskStatusEnum.COMPLETED, url: '/media/videos/101.mp4', created_at: '', updated_at: '' }],
          32: [],
        },
      },
    } as never)
    vi.mocked(api.mergeChapterVideos).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { chapter_id: 337, merged_url: '/media/videos/merged/chapter_337_merged.mp4', video_count: 2, total_duration: 9 },
    })
    vi.mocked(downloadFile).mockResolvedValue(undefined)
  })

  it('合并当前章节已有分镜后下载，不再下载选中的单个分镜', async () => {
    const wrapper = await mountPage()
    await flushPromises()

    const downloadButton = wrapper.findAll('button').find(button => button.text().includes('下载当前'))
    expect(downloadButton).toBeTruthy()
    await downloadButton!.trigger('click')
    await flushPromises()

    expect(api.mergeChapterVideos).toHaveBeenCalledWith(337)
    expect(downloadFile).toHaveBeenCalledWith(
      '/media/videos/merged/chapter_337_merged.mp4',
      '雾城-第12集-山雨欲来-完整视频.mp4',
    )
    expect(downloadFile).not.toHaveBeenCalledWith('/media/videos/100.mp4', expect.anything())
  })
})
