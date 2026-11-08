import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/api'
import { TaskStatusEnum, type RemakeProgressSnapshot } from '@/types'
import RemakeProgressPage from './RemakeProgressPage.vue'

const push = vi.fn()
const replace = vi.fn()

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { projectId: '28' } }),
  useRouter: () => ({ push, replace }),
}))

vi.mock('@/api', () => ({
  api: {
    remakeProjectProgress: vi.fn(),
    streamRemakeProjectProgress: vi.fn(),
    retryRemakeSource: vi.fn(),
  },
}))

function progressSnapshot(overrides: Partial<RemakeProgressSnapshot> = {}): RemakeProgressSnapshot {
  return {
    novel_id: 28,
    name: '酱板鸭',
    aggregate_status: 'processing',
    terminal: false,
    overall_progress: 42,
    source_summary: { total: 1, queued: 0, processing: 1, completed: 0, failed: 0 },
    sources: [{
      source_id: 9,
      chapter_id: 18,
      episode_number: 1,
      original_filename: '酱板鸭.mp4',
      media_status: 'processing',
      task: {
        id: 'task-1',
        status: TaskStatusEnum.PROCESSING,
        stage: 'detecting_scenes',
        progress: 42,
        error_message: null,
        updated_at: '2026-08-29T08:00:00+08:00',
      },
    }],
    entry_path: '/create/short-drama/manual/28',
    updated_at: '2026-08-29T08:00:00+08:00',
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.remakeProjectProgress).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: progressSnapshot(),
  })
})

describe('RemakeProgressPage', () => {
  it.each(['light', 'dark'])('shows retry errors and allows another attempt in %s mode', async theme => {
    document.documentElement.dataset.appTheme = theme
    const failed = progressSnapshot({ aggregate_status: 'failed', terminal: true })
    failed.sources[0].task!.status = TaskStatusEnum.FAILED
    failed.sources[0].task!.error_message = '原任务失败'
    vi.mocked(api.remakeProjectProgress).mockResolvedValue({ code: 0, message: 'ok', data: failed })
    let rejectRetry!: (reason: Error) => void
    vi.mocked(api.retryRemakeSource).mockImplementationOnce(() => new Promise((_resolve, reject) => {
      rejectRetry = reject
    }))
    const wrapper = mount(RemakeProgressPage)
    await flushPromises()
    const retry = () => wrapper.findAll('button').find(button => button.text().includes('重试'))!

    await retry().trigger('click')
    expect(retry().attributes('disabled')).toBeDefined()
    expect(retry().attributes('aria-busy')).toBe('true')
    await retry().trigger('click')
    expect(api.retryRemakeSource).toHaveBeenCalledOnce()
    rejectRetry(new Error('重制来源不存在'))
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toBe('重制来源不存在')
    expect(wrapper.text()).toContain('原任务失败')
    expect(retry().attributes('disabled')).toBeUndefined()

    vi.mocked(api.retryRemakeSource).mockResolvedValueOnce({ code: 0, message: 'ok', data: { source_id: 9, task_id: 'task-2', status: 'queued' } })
    vi.mocked(api.remakeProjectProgress).mockResolvedValueOnce({ code: 0, message: 'ok', data: progressSnapshot() })
    vi.mocked(api.streamRemakeProjectProgress).mockImplementation(async (_project, _callback, signal) => {
      await new Promise<void>(resolve => signal.addEventListener('abort', () => resolve(), { once: true }))
    })
    await retry().trigger('click')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('正在拆解视频')
    expect(api.retryRemakeSource).toHaveBeenCalledTimes(2)
    wrapper.unmount()
    delete document.documentElement.dataset.appTheme
  })

  it('shows persisted decomposition progress and only aborts the SSE observer on leave', async () => {
    let streamSignal: AbortSignal | undefined
    vi.mocked(api.streamRemakeProjectProgress).mockImplementation(async (_projectId, _onSnapshot, signal) => {
      streamSignal = signal
      await new Promise<void>(resolve => signal.addEventListener('abort', () => resolve(), { once: true }))
    })

    const wrapper = mount(RemakeProgressPage)
    await flushPromises()

    expect(wrapper.text()).toContain('正在拆解视频')
    expect(wrapper.text()).toContain('检测并切分镜头')
    expect(wrapper.text()).toContain('42%')
    expect(wrapper.text()).toContain('关闭或离开本页面不会中断后台任务')
    expect(api.streamRemakeProjectProgress).toHaveBeenCalledOnce()

    wrapper.unmount()
    expect(streamSignal?.aborted).toBe(true)
    expect(api.retryRemakeSource).not.toHaveBeenCalled()
  })

  it('enters the settings workspace after an SSE completion event', async () => {
    vi.mocked(api.streamRemakeProjectProgress).mockImplementation(async (_projectId, onSnapshot) => {
      onSnapshot(progressSnapshot({
        aggregate_status: 'completed',
        terminal: true,
        overall_progress: 100,
        source_summary: { total: 1, queued: 0, processing: 0, completed: 1, failed: 0 },
        sources: [{
          ...progressSnapshot().sources[0],
          media_status: 'completed',
          task: {
            ...progressSnapshot().sources[0].task!,
            status: TaskStatusEnum.COMPLETED,
            stage: 'completed',
            progress: 100,
          },
        }],
      }))
    })

    mount(RemakeProgressPage)
    await flushPromises()

    expect(replace).toHaveBeenCalledWith('/create/short-drama/manual/28')
  })
})
