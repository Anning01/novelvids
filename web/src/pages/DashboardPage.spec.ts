import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import AppButton from '@/components/AppButton.vue'
import DashboardPage from './DashboardPage.vue'

vi.mock('@/api', () => ({
  api: {
    novels: vi.fn(),
    deleteNovel: vi.fn(),
  },
}))

beforeEach(() => {
  vi.mocked(api.novels).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: {
      items: [],
      pagination: { total: 0, page: 1, page_size: 20, pages: 0 },
    },
  })
})

it('keeps project creation exclusively in the creation page', async () => {
  const wrapper = mount(DashboardPage, {
    global: {
      components: { AppButton },
      stubs: {
        RouterLink: {
          props: ['to'],
          template: '<a :href="to"><slot /></a>',
        },
      },
    },
  })
  await flushPromises()

  expect(wrapper.text()).not.toContain('新建项目')
  expect(wrapper.text()).not.toContain('创建项目')
  expect(wrapper.find('form').exists()).toBe(false)
  expect(wrapper.get('a[href="/create/short-drama"]').text()).toContain('前往创作')
})
