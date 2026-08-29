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
