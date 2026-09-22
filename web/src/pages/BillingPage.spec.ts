import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'
import { api } from '@/api'
import BillingPage from './BillingPage.vue'

vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      billingSummary: vi.fn(),
    billingProjects: vi.fn(),
    billingRecords: vi.fn(),
    billingRecordDetails: vi.fn(),
  },
    statusLabel: vi.fn((status?: number) => (status ? String(status) : '未知')),
  }
})

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
      global: {
        plugins: [createPinia()],
        stubs: { RouterLink: true, AppSelect: { template: '<div class="app-select-stub"><slot /></div>' } },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('总成本')
    expect(wrapper.text()).toContain('¥3.00')
  })

  it('shows one conversation row and loads its original records only when expanded', async () => {
    const group = { id: 20, novel_id: 1, task_type: 7, billing_type: 'text' as const, model: 'first、second',
      usage: { input_tokens: 3000, output_tokens: 200, requests: 6 }, cost: 0.3, currency: 'CNY',
      status: 3, statuses: [3, 4], created_at: '2026-09-22', updated_at: '2026-09-22',
      record_kind: 'agent_conversation' as const, conversation_id: 4, turn_count: 2, record_count: 2,
      pricing_snapshot: { discount: 0.5 } }
    vi.mocked(api.billingSummary).mockResolvedValue({ code: 0, message: '', data: {
      total_cost: 0.3, total_records: 2, by_billing_type: [], by_task_type: [], by_model: [], daily_trend: [],
    } })
    vi.mocked(api.billingProjects).mockResolvedValue({ code: 0, message: '', data: {
      items: [{ novel_id: 1, novel_name: '项目A', total_cost: 0.3, record_count: 2 }],
      pagination: { total: 1, page: 1, page_size: 100, pages: 1 },
    } })
    vi.mocked(api.billingRecords).mockResolvedValue({ code: 0, message: '', data: {
      items: [group], pagination: { total: 1, page: 1, page_size: 20, pages: 1 },
    } })
    vi.mocked(api.billingRecordDetails).mockResolvedValue({ code: 0, message: '', data: {
      items: [{ ...group, id: 19, model: 'first', cost: 0.1, record_kind: 'call' }, { ...group, model: 'second', cost: 0.2, record_kind: 'call' }],
      pagination: { total: 2, page: 1, page_size: 20, pages: 1 },
    } })
    const wrapper = mount(BillingPage, { global: { plugins: [createPinia()] } })
    await flushPromises()
    expect(wrapper.findAll('.data-table > tbody > tr')).toHaveLength(1)
    expect(wrapper.text()).toContain('会话 4 · 2 轮对话')
    expect(wrapper.text()).toContain('含失败记录')
    expect(wrapper.find('.discount-chip').exists()).toBe(false)
    expect(api.billingRecordDetails).not.toHaveBeenCalled()
    const toggle = wrapper.get('[aria-label="查看会话 4 费用明细"]')
    await toggle.trigger('click')
    await flushPromises()
    expect(api.billingRecordDetails).toHaveBeenCalledWith(20, { novel_id: 1, page: 1, page_size: 20 })
    expect(wrapper.get('[aria-label="会话费用明细"]').text()).toContain('共 2 条原始记录')
    await toggle.trigger('click')
    expect(wrapper.find('[aria-label="会话费用明细"]').exists()).toBe(false)
    wrapper.unmount()
  })
})
