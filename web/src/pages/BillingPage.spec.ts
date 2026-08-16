import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { api } from '@/api'
import BillingPage from './BillingPage.vue'

vi.mock('@/api', () => ({
  api: {
    billingSummary: vi.fn(),
    billingProjects: vi.fn(),
    billingRecords: vi.fn(),
  },
  statusLabel: vi.fn((status?: number) => (status ? String(status) : '未知')),
}))

describe('BillingPage', () => {
  it('渲染汇总卡片与项目成本表', async () => {
    vi.mocked(api.billingSummary).mockResolvedValue({
      code: 0, message: 'ok',
      data: { total_cost: 3.0035, total_records: 3, by_billing_type: [], by_task_type: [], by_model: [], daily_trend: [] },
    })
    vi.mocked(api.billingProjects).mockResolvedValue({
      code: 0, message: 'ok',
      data: { items: [{ novel_id: 1, novel_name: '项目A', total_cost: 3.0035, record_count: 3 }], pagination: { total: 1, page: 1, page_size: 20, pages: 1 } },
    })
    vi.mocked(api.billingRecords).mockResolvedValue({
      code: 0, message: 'ok',
      data: { items: [], pagination: { total: 0, page: 1, page_size: 20, pages: 0 } },
    })

    const wrapper = mount(BillingPage, {
      global: { stubs: { RouterLink: true, AppSelect: { template: '<div class="app-select-stub"><slot /></div>' } } },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('总成本')
    expect(wrapper.text()).toContain('¥3.00')
  })
})
