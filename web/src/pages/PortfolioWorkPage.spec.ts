import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import AppButton from '@/components/AppButton.vue'
import AppSelect from '@/components/AppSelect.vue'
import { finishedApi } from '@/features/finished-episodes/api'
import { finishedVersion } from '@/features/finished-episodes/fixtures'
import { workApi, type WorkDetail } from '@/features/portfolio/api'
import { appConfirm } from '@/shared/confirmDialog'
import PortfolioWorkPage from './PortfolioWorkPage.vue'

vi.mock('@/features/portfolio/api', async original => ({
  ...await original<typeof import('@/features/portfolio/api')>(),
  workApi: { detail: vi.fn(), action: vi.fn(), save: vi.fn(), publicMedia: vi.fn() },
}))
vi.mock('@/features/finished-episodes/api', async original => ({
  ...await original<typeof import('@/features/finished-episodes/api')>(),
  finishedApi: { versions: vi.fn() },
}))
vi.mock('@/shared/confirmDialog', () => ({ appConfirm: vi.fn() }))

const work: WorkDetail = {
  project_id: 9, title: '山海异闻录', description: '作品简介', category: '3D仙侠', tags: [], status: 'pending',
  featured: false, featured_order: 0, episode_count: 2, duration: 20, resolution: '1080P',
  cover_export_id: 3, cover_chapter_id: 1, producer: '林制作', archived_at: '2026-11-04T12:00:00Z',
  updated_at: '2026-11-04T12:00:00Z', last_action: 'submit', revision: 1, can_edit: true, can_manage: true,
  episodes: [
    { chapter_id: 1, number: 1, title: '山海', version: finishedVersion(3), published_id: null },
    { chapter_id: 2, number: 2, title: '异闻', version: finishedVersion(4), published_id: null },
  ],
}
const response = (data: WorkDetail) => ({ code: 0, message: '', data })
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(workApi.detail).mockResolvedValue(response(work))
  vi.mocked(finishedApi.versions).mockImplementation(async chapter => ({
    code: 0, message: '', data: chapter === 1 ? [finishedVersion(3), finishedVersion(2)] : [finishedVersion(4)],
  }))
  vi.mocked(appConfirm).mockResolvedValue(true)
})

async function render(path = '/finished-library/9') {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/finished-library/:projectId', name: 'work-detail', component: PortfolioWorkPage },
    { path: '/works/:projectId', name: 'public-work', component: PortfolioWorkPage },
    { path: '/finished-library', component: { template: '<div>Library</div>' } },
  ] })
  await router.push(path)
  const wrapper = mount(PortfolioWorkPage, { global: {
    plugins: [createPinia(), router], components: { AppButton }, stubs: {
      FinishedCover: true,
      ElDialog: { props: ['modelValue', 'title'], template: '<section v-if="modelValue" role="dialog" :aria-label="title"><slot /></section>' },
    },
  } })
  await flushPromises()
  return wrapper
}

it('honors a link to an older edit and publishes only the explicit episode version', async () => {
  const published = { ...work, status: 'public' as const, revision: 2 }
  vi.mocked(workApi.action).mockResolvedValue(response(published))
  const wrapper = await render('/finished-library/9?chapter=1&version=2')
  expect(wrapper.get('.work-version').text()).toContain('v2')
  expect(wrapper.findAll('.episode-row')).toHaveLength(2)
  expect(wrapper.find('.work-public-episodes').exists()).toBe(false)
  const settings = wrapper.get('.work-disclosure')
  expect(settings.attributes('aria-expanded')).toBe('false')
  await settings.trigger('click')
  expect(settings.attributes('aria-expanded')).toBe('true')
  expect(wrapper.text()).not.toContain('设为首页推荐')
  await wrapper.findAll('button').find(button => button.text() === '将当前播放版本设为公开版本')!.trigger('click')
  await wrapper.findAll('input[type="checkbox"]')[1]!.setValue(false)
  await wrapper.findAll('button').find(button => button.text() === '通过并公开')!.trigger('click')
  await flushPromises()
  expect(appConfirm).toHaveBeenCalledOnce()
  expect(workApi.action).toHaveBeenCalledWith(9, expect.objectContaining({ action: 'publish', revision: 1, export_ids: [2] }))
  expect(wrapper.text()).toContain('打开公开页面')
  wrapper.unmount()
})

it('renders the public viewer without management, editing or private version requests', async () => {
  vi.mocked(workApi.detail).mockResolvedValue(response({
    ...work, status: 'public', episode_count: 1, episodes: [work.episodes[1]!], can_edit: false, can_manage: false,
  }))
  const wrapper = await render('/works/9')
  expect(workApi.detail).toHaveBeenCalledWith(9, true, expect.any(AbortSignal))
  expect(finishedApi.versions).not.toHaveBeenCalled()
  expect(wrapper.findAll('.episode-row')).toHaveLength(1)
  expect(wrapper.text()).not.toContain('公开展示设置')
  expect(wrapper.text()).not.toContain('编辑资料')
  wrapper.unmount()
})

it.each(['light', 'dark'])('keeps the preview in place when opening and saving the compact editor (%s)', async theme => {
  document.documentElement.dataset.appTheme = theme
  const wrapper = await render('/finished-library/9?edit=1')
  const preview = wrapper.get('.work-preview').element
  const dialog = wrapper.get('[role="dialog"]')
  expect(dialog.attributes('aria-label')).toBe('编辑作品资料')
  expect(wrapper.find('.work-detail-grid form').exists()).toBe(false)
  vi.mocked(workApi.save).mockRejectedValueOnce(new Error('保存失败，请重试'))
  expect(dialog.get('.work-edit-type').text()).toContain('3D仙侠')
  expect(wrapper.findAllComponents(AppSelect).some(picker => picker.props('ariaLabel') === '作品类型')).toBe(false)
  await dialog.get('input').setValue('新作品名称')
  await dialog.get('form').trigger('submit')
  await flushPromises()
  expect(dialog.get('[role="alert"]').text()).toBe('保存失败，请重试')
  vi.mocked(workApi.save).mockResolvedValue(response({ ...work, title: '新作品名称', revision: 2 }))
  await dialog.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  expect(wrapper.get('.work-preview').element).toBe(preview)
  expect(wrapper.get('h1').text()).toBe('新作品名称')
  expect(vi.mocked(workApi.save).mock.lastCall?.[1]).not.toHaveProperty('category')
  wrapper.unmount()
})
