import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/api'
import AppSelect from '@/components/AppSelect.vue'
import CreationConfigBar from '@/components/CreationConfigBar.vue'
import CreationEntryShell from '@/components/CreationEntryShell.vue'
import RemakeWorkshopPage from './RemakeWorkshopPage.vue'

const push = vi.fn()

vi.mock('vue-router', () => ({
  useRouter: () => ({ push }),
}))

vi.mock('@/api', () => ({
  api: {
    remakeCapabilities: vi.fn(),
    uploadRemakeVideo: vi.fn(),
    releaseRemakeUpload: vi.fn(),
    remakeHistoryProjects: vi.fn(),
    remakeHistoryEpisodes: vi.fn(),
    createRemakeProject: vi.fn(),
  },
}))

const capabilities = {
  media: { extensions: ['mp4', 'mov'], max_bytes: 500 * 1024 * 1024, max_duration_seconds: 1200 },
  aspect_ratios: ['9:16', '16:9'],
  resolutions: ['720p', '1080p'],
  styles: [
    { key: 'auto', label: 'AI 识别风格' },
    { key: 'realistic-general', label: '写实通用' },
  ],
  source_modes: { single_upload: true, folder_upload: false, history: false },
}

beforeEach(() => {
  push.mockReset()
  vi.clearAllMocks()
  vi.mocked(api.remakeCapabilities).mockResolvedValue({ code: 0, message: 'ok', data: capabilities })
  vi.mocked(api.uploadRemakeVideo).mockResolvedValue({
    upload_token: '01916f1a-41aa-7000-8000-000000000001',
    original_filename: 'demo.mp4',
    storage_provider: 'local',
    object_key: 'remake/.staging/demo.mp4',
    size_bytes: 5,
    duration_seconds: 12,
    width: 1080,
    height: 1920,
    container_format: 'mp4',
    checksum: 'a'.repeat(64),
    status: 'ready',
    expires_at: '',
  })
  vi.mocked(api.createRemakeProject).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: {
      novel_id: 28,
      workflow_kind: 'remake',
      entry_path: '/create/remake/28/progress',
      sources: [{ source_id: 1, chapter_id: 2, episode_number: 1, task_id: 'task', status: 'queued' }],
    },
  })
  vi.mocked(api.remakeHistoryProjects).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: { items: [], pagination: { total: 0, page: 1, page_size: 20, pages: 0 } },
  })
  vi.mocked(api.remakeHistoryEpisodes).mockResolvedValue({ code: 0, message: 'ok', data: [] })
  vi.mocked(api.releaseRemakeUpload).mockResolvedValue({ code: 0, message: 'ok', data: null })
})

describe('RemakeWorkshopPage', () => {
  it('renders backend capabilities and clearly marks later source modes unavailable', async () => {
    const wrapper = mount(RemakeWorkshopPage)
    await flushPromises()

    expect(wrapper.findComponent(CreationEntryShell).exists()).toBe(true)
    expect(wrapper.findComponent(CreationConfigBar).exists()).toBe(true)
    expect(wrapper.findAllComponents(AppSelect)).toHaveLength(3)
    expect(wrapper.get('.creation-entry-heading').text()).toContain('重制精品短剧')
    expect(api.remakeCapabilities).toHaveBeenCalledOnce()
    expect(wrapper.get('[data-source-mode="single_upload"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[data-source-mode="folder_upload"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-source-mode="history"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('单视频不超过 500 MB，时长不超过 20 分钟')
    expect(wrapper.text()).toContain('AI 识别风格')
  })

  it('rejects an unsupported local file before making a request', async () => {
    const wrapper = mount(RemakeWorkshopPage)
    await flushPromises()
    const input = wrapper.get<HTMLInputElement>('input[type="file"]')

    Object.defineProperty(input.element, 'files', {
      configurable: true,
      value: [new File(['video'], 'demo.avi', { type: 'video/x-msvideo' })],
    })
    await input.trigger('change')

    expect(api.uploadRemakeVideo).not.toHaveBeenCalled()
    expect(wrapper.get('[role="alert"]').text()).toContain('仅支持 MP4 或 MOV')
  })

  it('uploads one video, creates an idempotent remake project and enters the workspace', async () => {
    const wrapper = mount(RemakeWorkshopPage)
    await flushPromises()
    const input = wrapper.get<HTMLInputElement>('input[type="file"]')
    const file = new File(['video'], 'demo.mp4', { type: 'video/mp4' })
    Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })

    await input.trigger('change')
    await flushPromises()
    await wrapper.get('input[name="projectName"]').setValue('新重制项目')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(api.uploadRemakeVideo).toHaveBeenCalledWith(file)
    expect(api.createRemakeProject).toHaveBeenCalledWith(expect.objectContaining({
      name: '新重制项目',
      source_mode: 'single_upload',
      aspect_ratio: '9:16',
      resolution: '720p',
      style_key: null,
      custom_style_prompt: null,
      idempotency_key: expect.any(String),
      sources: [{ episode_number: 1, upload_token: '01916f1a-41aa-7000-8000-000000000001' }],
    }))
    expect(push).toHaveBeenCalledWith('/create/remake/28/progress')
  })

  it('selects an available history episode and creates from its chapter snapshot', async () => {
    vi.mocked(api.remakeCapabilities).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { ...capabilities, source_modes: { ...capabilities.source_modes, history: true } },
    })
    vi.mocked(api.remakeHistoryProjects).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: {
        items: [{ id: 8, name: '旧短剧', cover: null, available_episode_count: 1 }],
        pagination: { total: 1, page: 1, page_size: 20, pages: 1 },
      },
    })
    vi.mocked(api.remakeHistoryEpisodes).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: [
        { chapter_id: 81, episode_number: 1, name: '第1集', duration_seconds: 60, size_bytes: 1024, scene_count: 8, available: true, unavailable_reason: null },
        { chapter_id: 82, episode_number: 2, name: '第2集', duration_seconds: 40, size_bytes: 512, scene_count: 5, available: false, unavailable_reason: '镜头 3 尚无已完成视频' },
      ],
    })
    const wrapper = mount(RemakeWorkshopPage)
    await flushPromises()

    await wrapper.get('[data-source-mode="history"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('短剧制作项目')
    await wrapper.get('[data-history-project="8"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-history-episode="82"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('镜头 3 尚无已完成视频')
    await wrapper.get('[data-history-episode="81"]').trigger('click')
    await wrapper.get('input[name="projectName"]').setValue('历史重制项目')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(api.createRemakeProject).toHaveBeenCalledWith(expect.objectContaining({
      name: '历史重制项目',
      source_mode: 'history',
      sources: [{ source_chapter_id: 81 }],
    }))
  })

  it('reads a folder, uploads videos by episode order and creates a multi-episode project', async () => {
    vi.mocked(api.remakeCapabilities).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { ...capabilities, source_modes: { ...capabilities.source_modes, folder_upload: true } },
    })
    vi.mocked(api.uploadRemakeVideo).mockImplementation(async file => ({
      upload_token: `token-${file.name}`,
      original_filename: file.name,
      storage_provider: 'local',
      object_key: `remake/.staging/${file.name}`,
      size_bytes: file.size,
      duration_seconds: 12,
      width: 1080,
      height: 1920,
      container_format: file.name.endsWith('.mov') ? 'mov' : 'mp4',
      checksum: 'a'.repeat(64),
      status: 'ready',
      expires_at: '',
    }))
    const wrapper = mount(RemakeWorkshopPage)
    await flushPromises()
    await wrapper.get('[data-source-mode="folder_upload"]').trigger('click')
    const input = wrapper.get<HTMLInputElement>('[data-folder-input]')
    const files = [
      new File(['3'], '第3集.mp4', { type: 'video/mp4' }),
      new File(['1'], 'EP01.mov', { type: 'video/quicktime' }),
      new File(['2'], '第2话.mp4', { type: 'video/mp4' }),
      new File(['note'], '说明.txt', { type: 'text/plain' }),
    ]
    Object.defineProperty(input.element, 'files', { configurable: true, value: files })

    await input.trigger('change')
    await flushPromises()

    expect(api.uploadRemakeVideo).toHaveBeenCalledTimes(3)
    expect(wrapper.text()).toContain('非 MP4/MOV 文件，已忽略')
    const rows = wrapper.findAll('[data-folder-episode]')
    expect(rows.map(row => row.attributes('data-folder-episode'))).toEqual(['1', '2', '3'])
    await wrapper.get('input[name="projectName"]').setValue('三集重制')
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(api.createRemakeProject).toHaveBeenCalledWith(expect.objectContaining({
      source_mode: 'folder_upload',
      sources: [
        { episode_number: 1, upload_token: 'token-EP01.mov' },
        { episode_number: 2, upload_token: 'token-第2话.mp4' },
        { episode_number: 3, upload_token: 'token-第3集.mp4' },
      ],
    }))
  })

  it('blocks duplicate folder episodes before upload', async () => {
    vi.mocked(api.remakeCapabilities).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { ...capabilities, source_modes: { ...capabilities.source_modes, folder_upload: true } },
    })
    const wrapper = mount(RemakeWorkshopPage)
    await flushPromises()
    await wrapper.get('[data-source-mode="folder_upload"]').trigger('click')
    const input = wrapper.get<HTMLInputElement>('[data-folder-input]')
    Object.defineProperty(input.element, 'files', {
      configurable: true,
      value: [
        new File(['1'], '第1集.mp4', { type: 'video/mp4' }),
        new File(['1'], 'EP01.mov', { type: 'video/quicktime' }),
      ],
    })

    await input.trigger('change')
    await flushPromises()

    expect(api.uploadRemakeVideo).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('第 1 集重复')
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()
  })

  it('retries only the failed folder file', async () => {
    vi.mocked(api.remakeCapabilities).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { ...capabilities, source_modes: { ...capabilities.source_modes, folder_upload: true } },
    })
    let secondAttempts = 0
    vi.mocked(api.uploadRemakeVideo).mockImplementation(async file => {
      if (file.name === '第2集.mp4' && secondAttempts++ === 0) throw new Error('临时网络错误')
      return {
        upload_token: `token-${file.name}`,
        original_filename: file.name,
        storage_provider: 'local',
        object_key: `remake/.staging/${file.name}`,
        size_bytes: file.size,
        duration_seconds: 12,
        width: 1080,
        height: 1920,
        container_format: 'mp4',
        checksum: 'a'.repeat(64),
        status: 'ready',
        expires_at: '',
      }
    })
    const wrapper = mount(RemakeWorkshopPage)
    await flushPromises()
    await wrapper.get('[data-source-mode="folder_upload"]').trigger('click')
    const input = wrapper.get<HTMLInputElement>('[data-folder-input]')
    Object.defineProperty(input.element, 'files', {
      configurable: true,
      value: [
        new File(['1'], '第1集.mp4', { type: 'video/mp4' }),
        new File(['2'], '第2集.mp4', { type: 'video/mp4' }),
      ],
    })
    await input.trigger('change')
    await flushPromises()

    expect(wrapper.text()).toContain('临时网络错误')
    await wrapper.get('button.app-button--secondary').trigger('click')
    await flushPromises()

    expect(api.uploadRemakeVideo).toHaveBeenCalledTimes(3)
    expect(wrapper.text()).not.toContain('临时网络错误')
  })
})
