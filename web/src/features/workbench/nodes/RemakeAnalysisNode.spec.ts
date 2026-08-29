import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { TaskStatusEnum } from '@/types'
import { useWorkbenchStore } from '../store/workbenchStore'
import RemakeAnalysisNode from './RemakeAnalysisNode.vue'

vi.mock('@/api', () => ({ api: {}, mediaUrl: (value: string) => value, sleep: vi.fn() }))

let store: ReturnType<typeof useWorkbenchStore>
beforeEach(() => {
  setActivePinia(createPinia())
  store = useWorkbenchStore()
})

function mountNode(task: Record<string, unknown>) {
  return mount(RemakeAnalysisNode, {
    props: {
      id: 'remake-analysis-task-1',
      type: 'ai_decomposition',
      selected: false,
      data: { title: 'AI 视频拆解', sourceId: 21, task },
    } as never,
    global: { stubs: { WorkbenchNodeFrame: { template: '<article><slot /></article>' } } },
  })
}

it('shows localized stage and progress for an active task', () => {
  const wrapper = mountNode({ id: 'task-1', status: TaskStatusEnum.PROCESSING, stage: 'detecting_scenes', progress: 42 })

  expect(wrapper.text()).toContain('检测镜头切分')
  expect(wrapper.text()).toContain('42%')
  expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBe('42')
  expect(wrapper.find('button').exists()).toBe(false)
})

it('shows safe error and retries a failed task', async () => {
  const retry = vi.spyOn(store, 'retryRemakeAnalysis').mockResolvedValue()
  const wrapper = mountNode({
    id: 'task-1',
    status: TaskStatusEnum.FAILED,
    stage: 'failed',
    progress: 54,
    error_message: '拆解失败，请重试',
  })

  expect(wrapper.get('[role="alert"]').text()).toBe('拆解失败，请重试')
  await wrapper.get('button').trigger('click')
  expect(retry).toHaveBeenCalledOnce()
})
