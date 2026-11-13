import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import AppButton from '@/components/AppButton.vue'
import FinishedEpisodesPage from './FinishedEpisodesPage.vue'
import WorkCard from '@/features/portfolio/WorkCard.vue'
import { workApi, type WorkSummary } from '@/features/portfolio/api'

vi.mock('@/features/portfolio/api', async original => ({
  ...await original<typeof import('@/features/portfolio/api')>(), workApi: { list: vi.fn() },
}))
const work: WorkSummary = {
  project_id: 9, title: '山海异闻录', category: '短剧', tags: ['悬疑'], status: 'pending', featured: false, featured_order: 0,
  episode_count: 2, duration: 60, resolution: '1080P', cover_export_id: 3, producer: '林制作',
  production_seconds: 2 * 86400 + 3 * 3600, recorded_cost: 104.04, cost_scope: 'project',
  archived_at: '2026-11-04T12:00:00Z', updated_at: '2026-11-04T12:00:00Z', last_action: 'submit',
}
const result = {
  code: 0, message: '', data: {
    items: [work], total: 1, counts: { all: 1, pending: 1, public: 0, private: 0, featured: 0 },
    recent: [work], categories: ['短剧'], producers: [], archive_options: [],
  },
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(workApi.list).mockResolvedValue(result)
})
async function render() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/finished-library', component: FinishedEpisodesPage },
    { path: '/finished-library/:projectId', name: 'work-detail', component: { template: '<div>Details</div>' } },
    { path: '/', component: { template: '<div>Home</div>' } },
  ] })
  await router.push('/finished-library')
  const wrapper = mount(FinishedEpisodesPage, { global: {
    plugins: [createPinia(), router], components: { AppButton }, stubs: { FinishedCover: true },
  } })
  await flushPromises()
  return { wrapper, router }
}

it.each(['light', 'dark'])('shows two episodes as one project card and opens its detail route (%s)', async theme => {
  document.documentElement.dataset.appTheme = theme
  const { wrapper, router } = await render()
  expect(wrapper.get('h1').text()).toBe('作品库')
  expect(wrapper.findAll('button').some(button => button.text() === '归档作品')).toBe(false)
  const cards = wrapper.findAllComponents(WorkCard)
  expect(cards).toHaveLength(1)
  expect(cards[0]!.text()).toContain('2 集')
  const facts = cards[0]!.get('.work-production').text()
  expect(facts).toContain('制作人林制作')
  expect(facts).toContain('制作耗时2 天 3 小时')
  expect(facts).toContain('项目已花费¥104.04')
  const actions = cards[0]!.get('.work-actions').findAll('a')
  expect(actions).toHaveLength(1)
  expect(actions[0]!.text()).toBe('查看作品')
  await actions[0]!.trigger('click')
  await flushPromises()
  expect(router.currentRoute.value.params.projectId).toBe('9')
  wrapper.unmount()
})

it('shows pending settlement on the work card instead of the partial amount', async () => {
  vi.mocked(workApi.list).mockResolvedValue({ ...result, data: { ...result.data, items: [{ ...work, pending_cost: true }] } })
  const { wrapper } = await render()
  const facts = wrapper.get('.work-production').text()
  expect(facts).toContain('待结算')
  expect(facts).not.toContain('¥104.04')
})

it('filters by review status and retries a failed request', async () => {
  const { wrapper } = await render()
  vi.mocked(workApi.list).mockRejectedValueOnce(new Error('Network unavailable'))
  await wrapper.findAll('button').find(button => button.text() === '审核待处理作品')!.trigger('click')
  await flushPromises()
  expect(workApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'pending' }), expect.any(AbortSignal))
  expect(wrapper.get('[role="alert"]').text()).toContain('Network unavailable')
  await wrapper.get('[role="alert"] button').trigger('click')
  await flushPromises()
  expect(wrapper.get('.work-card h2').text()).toBe(work.title)
  wrapper.unmount()
})

it('does not show the cost field when the server withholds it', async () => {
  vi.mocked(workApi.list).mockResolvedValue({
    ...result, data: { ...result.data, items: [{ ...work, recorded_cost: null, cost_scope: null }] },
  })
  const { wrapper } = await render()
  expect(wrapper.get('.work-production').text()).not.toContain('花费')
  wrapper.unmount()
})
