import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import { setLocale } from '@/i18n'
import { useAuthStore } from '@/features/auth/authStore'
import { appConfirm } from '@/shared/confirmDialog'
import type { ProjectOverview, ProjectOverviewItem } from '@/types'
import DashboardPage from './DashboardPage.vue'

vi.mock('@/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/api')>()
  return { ...original, api: { ...original.api, projectOverview: vi.fn(), deleteNovel: vi.fn() } }
})
vi.mock('@/shared/confirmDialog', () => ({ appConfirm: vi.fn() }))
vi.mock('@/shared/notice', () => ({ notice: { error: vi.fn() } }))

function project(id: number, name: string, state: ProjectOverviewItem['production']['state'] = 'not_started'): ProjectOverviewItem {
  return { id, name, author: 'Agent 创建', tags: ['科幻'], created_at: '2026-10-20 10:00:00', updated_at: '2026-10-25 10:00:00', production: {
    chapter_count: 5, storyboard_chapter_count: 2, completed_episode_count: state === 'ready' ? 1 : 0,
    completed_shot_count: state === 'ready' ? 3 : 0, shot_count: state === 'not_started' ? 0 : 3,
    asset_count: 8, video_seconds: state === 'ready' ? 125 : 0, unknown_duration_count: 0,
    latest_episode_number: state === 'ready' ? 1 : null, latest_activity_at: `2026-10-${20 + id} 10:00:00`, state,
  } }
}

function response(items: ProjectOverviewItem[]): { code: number; message: string; data: ProjectOverview } {
  return { code: 0, message: 'ok', data: { items, summary: {
    project_count: items.length, chapter_count: items.reduce((n, p) => n + p.production.chapter_count, 0),
    asset_count: items.reduce((n, p) => n + p.production.asset_count, 0),
    video_seconds: items.reduce((n, p) => n + p.production.video_seconds, 0), unknown_duration_count: 0,
  } } }
}

function render() {
  return mount(DashboardPage, { attachTo: document.body, global: { stubs: {
    RouterLink: { props: ['to'], template: '<a :href="typeof to === \'string\' ? to : \'#project\'"><slot /></a>' },
    AppSelect: {
      props: ['modelValue', 'options', 'ariaLabel'], emits: ['update:modelValue'],
      template: '<select :aria-label="ariaLabel" :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><option v-for="option in options" :key="option.value" :value="option.value">{{ option.label }}</option></select>',
    },
  } } })
}

beforeEach(() => {
  document.body.innerHTML = ''
  setActivePinia(createPinia())
  useAuthStore().enabled = false
  setLocale('zh')
  vi.clearAllMocks()
  vi.mocked(api.projectOverview).mockResolvedValue(response([project(1, '星河来信', 'ready'), project(2, '未开始的故事')]))
})

it('shows a creation link, real totals and video episode counts without invented percentages', async () => {
  const wrapper = render()
  await flushPromises()
  expect(wrapper.get('a[href="/create/short-drama"]').text()).toContain('新建项目')
  expect(wrapper.find('form').exists()).toBe(false)
  expect(wrapper.findAll('.projects-summary__item')).toHaveLength(4)
  expect(wrapper.findAll('.project-overview-card')).toHaveLength(2)
  expect(wrapper.text()).toContain('已完成 1 集')
  expect(wrapper.find('[role="progressbar"]').exists()).toBe(false)
  expect(wrapper.text()).not.toContain('%')
  expect(wrapper.get('.projects-summary__item.is-chapters p').text()).toBe('10')
  wrapper.unmount()
})

it('filters by name, type and state without changing all-project totals', async () => {
  const manual = { ...project(3, '另一封信', 'in_progress'), author: '人工创建' }
  vi.mocked(api.projectOverview).mockResolvedValue(response([project(1, '星河来信', 'ready'), manual]))
  const wrapper = render()
  await flushPromises()
  await wrapper.get('select[aria-label="项目类型"]').setValue('manual')
  expect(wrapper.findAll('.project-overview-card')).toHaveLength(1)
  expect(wrapper.text()).toContain('另一封信')
  expect(wrapper.get('.projects-summary__item.is-projects p').text()).toBe('2')
  await wrapper.get('input[type="search"]').setValue('不存在')
  expect(wrapper.text()).toContain('没有找到匹配的项目')
  await wrapper.get('.projects-page__empty button').trigger('click')
  expect(wrapper.findAll('.project-overview-card')).toHaveLength(2)
  await wrapper.get('select[aria-label="创作状态"]').setValue('ready')
  expect(wrapper.findAll('.project-overview-card')).toHaveLength(1)
  expect(wrapper.get('.project-overview-card h2').text()).toBe('星河来信')
  wrapper.unmount()
})

it('sorts by recent production activity by default and supports name sorting', async () => {
  const wrapper = render()
  await flushPromises()
  expect(wrapper.findAll('.project-overview-card h2')[0]?.text()).toBe('未开始的故事')
  await wrapper.get('select[aria-label="项目排序"]').setValue('name')
  expect(wrapper.findAll('.project-overview-card h2').map(node => node.text())).toEqual(['星河来信', '未开始的故事'].sort((a, b) => a.localeCompare(b)))
  wrapper.unmount()
})

it('isolates delete from navigation, requires confirmation and refreshes totals after success', async () => {
  vi.mocked(appConfirm).mockResolvedValue(true)
  vi.mocked(api.deleteNovel).mockResolvedValue({ code: 0, message: 'ok', data: null })
  const wrapper = render()
  await flushPromises()
  const card = wrapper.findAll('.project-overview-card')[0]!
  expect(card.find('[role="menuitem"]').exists()).toBe(false)
  await card.get('[aria-haspopup="menu"]').trigger('click')
  expect(card.get('.project-overview-card__link').find('[role="menuitem"]').exists()).toBe(false)
  vi.mocked(api.projectOverview).mockResolvedValue(response([project(1, '星河来信', 'ready')]))
  await card.get('[role="menuitem"]').trigger('click')
  await flushPromises()
  expect(appConfirm).toHaveBeenCalledOnce()
  expect(api.deleteNovel).toHaveBeenCalledWith(2)
  expect(wrapper.get('.projects-summary__item.is-projects p').text()).toBe('1')
  wrapper.unmount()
})

it('supports Escape and cancelled confirmation without deleting', async () => {
  vi.mocked(appConfirm).mockResolvedValue(false)
  const wrapper = render()
  await flushPromises()
  const card = wrapper.findAll('.project-overview-card')[0]!
  await card.get('[aria-haspopup="menu"]').trigger('click')
  await card.get('[role="menuitem"]').trigger('keydown', { key: 'Escape' })
  expect(card.find('[role="menuitem"]').exists()).toBe(false)
  await card.get('[aria-haspopup="menu"]').trigger('click')
  await card.get('[role="menuitem"]').trigger('click')
  await flushPromises()
  expect(api.deleteNovel).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('shows real zeros and the existing creation route for an empty library', async () => {
  vi.mocked(api.projectOverview).mockResolvedValue(response([]))
  const wrapper = render()
  await flushPromises()
  expect(wrapper.text()).toContain('暂无项目')
  expect(wrapper.get('.projects-summary__item.is-runtime p').text()).toBe('0分钟')
  expect(wrapper.get('.projects-page__empty a').attributes('href')).toBe('/create/short-drama')
  wrapper.unmount()
})

it('distinguishes failed loading from an empty library and can retry', async () => {
  vi.mocked(api.projectOverview).mockRejectedValueOnce(new Error('Offline'))
  const wrapper = render()
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('Offline')
  expect(wrapper.text()).not.toContain('暂无项目')
  await wrapper.get('[role="alert"] button').trigger('click')
  await flushPromises()
  expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  expect(wrapper.findAll('.project-overview-card')).toHaveLength(2)
  wrapper.unmount()
})

it('does not expose create or delete controls to a viewer', async () => {
  const auth = useAuthStore()
  auth.enabled = true
  auth.memberships = [{ team_id: 1, role: 'viewer' } as typeof auth.memberships[number]]
  auth.activeTeamId = 1
  const wrapper = render()
  await flushPromises()
  expect(wrapper.find('a[href="/create/short-drama"]').exists()).toBe(false)
  expect(wrapper.find('[aria-haspopup="menu"]').exists()).toBe(false)
  wrapper.unmount()
})

it('exposes full long titles, English labels and unknown actual runtime', async () => {
  const value = project(1, 'A very long complete project title that must remain accessible', 'ready')
  value.production.unknown_duration_count = 1
  value.production.video_seconds = 0
  const result = response([value])
  result.data.summary.unknown_duration_count = 1
  vi.mocked(api.projectOverview).mockResolvedValue(result)
  setLocale('en')
  const wrapper = render()
  await flushPromises()
  expect(wrapper.text()).toContain('My projects')
  expect(wrapper.get('a[href="/create/short-drama"]').text()).toContain('New project')
  expect(wrapper.get('.project-overview-card h2').attributes('title')).toBe(value.name)
  expect(wrapper.text()).toContain('Unconfirmed')
  expect(wrapper.text()).toContain('Actual runtime is unconfirmed')
  wrapper.unmount()
})

it('paginates projects and resets the page when a filter changes', async () => {
  vi.mocked(api.projectOverview).mockResolvedValue(response(Array.from({ length: 15 }, (_, i) => project(i + 1, `Project ${i + 1}`))))
  const wrapper = render()
  await flushPromises()
  expect(wrapper.findAll('.project-overview-card')).toHaveLength(12)
  await wrapper.get('.app-pagination__controls button:last-child').trigger('click')
  expect(wrapper.findAll('.project-overview-card')).toHaveLength(3)
  await wrapper.get('input[type="search"]').setValue('Project 15')
  expect(wrapper.findAll('.project-overview-card')).toHaveLength(1)
  expect(wrapper.get('.project-overview-card h2').text()).toBe('Project 15')
  wrapper.unmount()
})

it('does not show an old team response after the active team changes', async () => {
  let finishOld: ((result: ReturnType<typeof response>) => void) | undefined
  vi.mocked(api.projectOverview).mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
  const wrapper = render()
  useAuthStore().activeTeamId = 2
  await flushPromises()
  expect(wrapper.text()).toContain('星河来信')
  finishOld?.(response([project(3, 'Old team project')]))
  await flushPromises()
  expect(wrapper.text()).not.toContain('Old team project')
  wrapper.unmount()
})

it('refreshes production stats on focus and removes its listener on unmount', async () => {
  const wrapper = render()
  await flushPromises()
  vi.mocked(api.projectOverview).mockResolvedValue(response([project(3, '刚完成的视频', 'ready')]))
  window.dispatchEvent(new Event('focus'))
  await flushPromises()
  expect(wrapper.findAll('.project-overview-card')).toHaveLength(1)
  expect(wrapper.text()).toContain('刚完成的视频')
  wrapper.unmount()
  const count = vi.mocked(api.projectOverview).mock.calls.length
  window.dispatchEvent(new Event('focus'))
  await flushPromises()
  expect(api.projectOverview).toHaveBeenCalledTimes(count)
})
