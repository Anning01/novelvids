import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia } from 'pinia'
import { exportApi } from '@/features/video-export/api'
import ShortDramaVideoPage from './ShortDramaVideoPage.vue'
import { api } from '@/api'
import { downloadFile } from '@/shared/downloadFile'
import { downloadVideoZip } from '@/shared/downloadZip'
import AppButton from '@/components/AppButton.vue'
import EditorWorkspace from '@/features/video-editor/EditorWorkspace.vue'
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
vi.mock('@/shared/downloadZip', () => ({ downloadVideoZip: vi.fn() }))

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
      plugins: [router, createPinia()],
      components: { AppButton },
      stubs: {
        EditorWorkspace: { props: ['chapterId', 'projectId', 'filename'], template: '<div class="editor-workspace"></div>', expose: ['openExport'], methods: { openExport() {} } },
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
    vi.spyOn(exportApi, 'list').mockResolvedValue({ data: [] })
    vi.spyOn(exportApi, 'models').mockResolvedValue({ data: [] })
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
    vi.mocked(downloadVideoZip).mockResolvedValue(undefined)
  })

  it('opens edit export separately from downloading original shots', async () => {
    const wrapper = await mountPage(); await flushPromises()
    expect(wrapper.findComponent(EditorWorkspace).exists()).toBe(true)
    const exportButton = wrapper.findAll('button').find(button => button.text().includes('导出成片'))
    expect(exportButton).toBeTruthy()
    expect(api.mergeChapterVideos).not.toHaveBeenCalled()
    expect(downloadVideoZip).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('defaults to numbered shot ZIP, preserving scene order and requiring no merge request', async () => {
    const wrapper = await mountPage(); await flushPromises()
    await wrapper.get('button[aria-label="按序号打包下载分镜视频"]').trigger('click'); await flushPromises()
    expect(downloadVideoZip).toHaveBeenCalledWith([
      { url: '/media/videos/100.mp4', filename: '001-分镜1.mp4' },
      { url: '/media/videos/101.mp4', filename: '002-分镜2.mp4' },
    ], '雾城-第12集-山雨欲来-分镜视频.zip', expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(api.mergeChapterVideos).not.toHaveBeenCalled()
    expect(downloadFile).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('opens the video workspace without the episode enhancement panel or its background requests', async () => {
    const wrapper = await mountPage()
    await flushPromises()
    expect(wrapper.text()).not.toContain('高清成片')
    expect(wrapper.text()).not.toContain('准备当前原片')
    expect(exportApi.list).not.toHaveBeenCalled()
    expect(exportApi.models).not.toHaveBeenCalled()
    expect(wrapper.findComponent(EditorWorkspace).exists()).toBe(true)
    expect(wrapper.find('button[aria-label="按序号打包下载分镜视频"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('shows progress and cancels the browser download when leaving the page', async () => {
    let signal: AbortSignal | undefined
    vi.mocked(downloadVideoZip).mockImplementation(async (_files, _name, options) => {
      signal = options?.signal
      options?.onProgress?.(1, 2)
      await new Promise<void>(resolve => signal?.addEventListener('abort', () => resolve(), { once: true }))
    })
    const wrapper = await mountPage(); await flushPromises()
    await wrapper.get('button[aria-label="按序号打包下载分镜视频"]').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('正在打包 1/2')
    expect(wrapper.find('button[aria-label="按序号打包下载分镜视频"]').attributes('disabled')).toBeDefined()
    wrapper.unmount(); await flushPromises()
    expect(signal?.aborted).toBe(true)
    expect(api.mergeChapterVideos).not.toHaveBeenCalled()
  })

  it('downloads only real media and does not collapse the saved editing timeline', async () => {
    const wrapper = await mountPage(); await flushPromises()
    await wrapper.get('button[aria-label="按序号打包下载分镜视频"]').trigger('click'); await flushPromises()
    expect(downloadVideoZip).toHaveBeenCalledWith(expect.arrayContaining([
      { url: '/media/videos/100.mp4', filename: '001-分镜1.mp4' },
    ]), expect.any(String), expect.any(Object))
    expect(wrapper.findComponent(EditorWorkspace).exists()).toBe(true)
    wrapper.unmount()
  })

  it('does not display a chapter from another project when the URL carries its ID', async () => {
    const wrapper = await mountPage(); await flushPromises()
    await wrapper.vm.$router.push('/create/short-drama/video/7?chapter=999')
    await flushPromises()
    expect(wrapper.findComponent(EditorWorkspace).props('chapterId')).toBe(337)
    wrapper.unmount()
  })
})
