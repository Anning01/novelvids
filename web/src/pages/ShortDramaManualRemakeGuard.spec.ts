import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import { api } from '@/api'
import ShortDramaManualPage from './ShortDramaManualPage.vue'

const replace = vi.fn()

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { projectId: '28' }, query: {} }),
  useRouter: () => ({ push: vi.fn(), replace, back: vi.fn() }),
}))

vi.mock('@/api', () => ({
  api: {
    novelMeta: vi.fn(),
    chapters: vi.fn(),
    remakeProjectProgress: vi.fn(),
    assets: vi.fn(),
  },
  sleep: vi.fn(),
  statusLabel: vi.fn(() => ''),
}))

it('redirects an unfinished remake away from the empty settings workspace', async () => {
  vi.mocked(api.novelMeta).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: {
      id: 28,
      name: '酱板鸭',
      author: '重制工坊',
      workflow_kind: 'remake',
      content_length: 0,
      created_at: '',
      updated_at: '',
    },
  })
  vi.mocked(api.chapters).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: { items: [], pagination: { total: 0, page: 1, page_size: 100, pages: 0 } },
  })
  vi.mocked(api.remakeProjectProgress).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: {
      novel_id: 28,
      name: '酱板鸭',
      aggregate_status: 'processing',
      terminal: false,
      overall_progress: 42,
      source_summary: { total: 1, queued: 0, processing: 1, completed: 0, failed: 0 },
      sources: [],
      entry_path: '/create/short-drama/manual/28',
      updated_at: '',
    },
  })

  mount(ShortDramaManualPage, {
    global: {
      stubs: {
        ShortDramaWorkspaceShell: { template: '<div><slot /></div>' },
        AssetCreateDialog: true,
        AssetBatchGenerateDialog: true,
      },
    },
  })
  await flushPromises()

  expect(replace).toHaveBeenCalledWith({
    name: 'remake-progress',
    params: { projectId: 28 },
  })
  expect(api.assets).not.toHaveBeenCalled()
})
