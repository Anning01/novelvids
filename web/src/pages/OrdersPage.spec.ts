import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { Pinia } from 'pinia'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import OrdersPage from './OrdersPage.vue'
import { api } from '@/api'
import { useAuthStore } from '@/features/auth/authStore'
import type { RechargeOrderItem } from '@/types'

function mountPage(pinia: Pinia = createPinia()) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: OrdersPage }],
  })
  return mount(OrdersPage, { global: { plugins: [pinia, router] } })
}

const mockOrders: RechargeOrderItem[] = [
  {
    id: 101,
    out_trade_no: 'REC20261106_001',
    team_id: 1,
    team_name: '短剧先锋队',
    user_id: 10,
    username: 'creator10',
    nickname: '张导',
    amount: '50.00',
    status: 'pending',
    payment_method: 'wechat_native',
    code_url: 'weixin://wxpay/bizpayurl?pr=mock123',
    created_at: '2026-11-06T10:00:00Z',
    note: '线上首充',
  },
  {
    id: 102,
    out_trade_no: 'REC20261106_002',
    team_id: 2,
    team_name: '特效冲锋队',
    user_id: 11,
    username: 'artist11',
    nickname: '李美工',
    amount: '100.00',
    status: 'paid',
    payment_method: 'wechat_native',
    transaction_id: 'TXN_WX_998877',
    created_at: '2026-11-06T09:00:00Z',
    paid_at: '2026-11-06T09:02:15Z',
    note: '活动赠送',
  },
]

describe('OrdersPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('renders orders list with order numbers, teams, amounts and status badges', async () => {
    const listSpy = vi.spyOn(api, 'rechargeOrders').mockResolvedValue({
      data: {
        items: mockOrders,
        pagination: { total: 2, page: 1, page_size: 20, pages: 1 },
      },
    } as never)

    const wrapper = mountPage()
    await flushPromises()

    expect(listSpy).toHaveBeenCalledWith({ page: 1, page_size: 20, status: undefined, search: undefined })
    expect(wrapper.text()).toContain('REC20261106_001')
    expect(wrapper.text()).toContain('REC20261106_002')
    expect(wrapper.text()).toContain('短剧先锋队')
    expect(wrapper.text()).toContain('特效冲锋队')
    expect(wrapper.text()).toContain('¥ 50.00')
    expect(wrapper.text()).toContain('¥ 100.00')
    expect(wrapper.text()).toContain('待支付')
    expect(wrapper.text()).toContain('已支付')
  })

  it('shows user column when super admin is logged in', async () => {
    vi.spyOn(api, 'rechargeOrders').mockResolvedValue({
      data: {
        items: mockOrders,
        pagination: { total: 2, page: 1, page_size: 20, pages: 1 },
      },
    } as never)

    const pinia = createPinia()
    const auth = useAuthStore(pinia)
    auth.user = { id: 1, username: 'admin', is_super_admin: true, nickname: '超管' } as never

    const wrapper = mountPage(pinia)
    await flushPromises()

    expect(wrapper.text()).toContain('充值用户')
    expect(wrapper.text()).toContain('张导')
    expect(wrapper.text()).toContain('李美工')
  })

  it('hides user column for ordinary users', async () => {
    vi.spyOn(api, 'rechargeOrders').mockResolvedValue({
      data: {
        items: mockOrders,
        pagination: { total: 2, page: 1, page_size: 20, pages: 1 },
      },
    } as never)

    const pinia = createPinia()
    const auth = useAuthStore(pinia)
    auth.user = { id: 10, username: 'creator10', is_super_admin: false, nickname: '张导' } as never

    const wrapper = mountPage(pinia)
    await flushPromises()

    expect(wrapper.text()).not.toContain('充值用户')
  })

  it('filters by status tab and triggers reload', async () => {
    const listSpy = vi.spyOn(api, 'rechargeOrders').mockResolvedValue({
      data: {
        items: [mockOrders[0]],
        pagination: { total: 1, page: 1, page_size: 20, pages: 1 },
      },
    } as never)

    const wrapper = mountPage()
    await flushPromises()

    const pendingTab = wrapper.findAll('.orders-tab-btn').find(btn => btn.text() === '待支付')
    expect(pendingTab).toBeDefined()
    await pendingTab?.trigger('click')
    await flushPromises()

    expect(listSpy).toHaveBeenLastCalledWith({
      page: 1,
      page_size: 20,
      status: 'pending',
      search: undefined,
    })
  })

  it('searches by keyword and triggers reload', async () => {
    const listSpy = vi.spyOn(api, 'rechargeOrders').mockResolvedValue({
      data: {
        items: [mockOrders[1]],
        pagination: { total: 1, page: 1, page_size: 20, pages: 1 },
      },
    } as never)

    const wrapper = mountPage()
    await flushPromises()

    const searchInput = wrapper.find('.orders-search-input')
    await searchInput.setValue('冲锋队')
    await wrapper.find('.orders-search-form').trigger('submit')
    await flushPromises()

    expect(listSpy).toHaveBeenLastCalledWith({
      page: 1,
      page_size: 20,
      status: undefined,
      search: '冲锋队',
    })
  })

  it('actively syncs order status when clicking sync button', async () => {
    vi.spyOn(api, 'rechargeOrders').mockResolvedValue({
      data: {
        items: [{ ...mockOrders[0] }],
        pagination: { total: 1, page: 1, page_size: 20, pages: 1 },
      },
    } as never)
    const syncSpy = vi.spyOn(api, 'syncRechargeOrder').mockResolvedValue({
      data: {
        ...mockOrders[0],
        status: 'paid',
        paid_at: '2026-11-06T10:05:00Z',
        transaction_id: 'WX_ACTIVE_SYNC_123',
      },
    } as never)

    const wrapper = mountPage()
    await flushPromises()

    const syncBtn = wrapper.find('.sync-btn')
    expect(syncBtn.exists()).toBe(true)
    await syncBtn.trigger('click')
    await flushPromises()

    expect(syncSpy).toHaveBeenCalledWith('REC20261106_001')
    expect(wrapper.text()).toContain('已支付')
  })

  it('shows refund button for super admin on paid orders and submits refund', async () => {
    vi.spyOn(api, 'rechargeOrders').mockResolvedValue({
      data: {
        items: [mockOrders[1]], // paid order
        pagination: { total: 1, page: 1, page_size: 20, pages: 1 },
      },
    } as never)
    const refundSpy = vi.spyOn(api, 'refundRechargeOrder').mockResolvedValue({
      data: {
        ...mockOrders[1],
        status: 'refunded',
        refund_id: 'REF_TEST_123',
        refund_reason: '协商退款',
      },
    } as never)

    const pinia = createPinia()
    const auth = useAuthStore(pinia)
    auth.user = { id: 1, username: 'admin', is_super_admin: true, nickname: '超管' } as never

    const wrapper = mountPage(pinia)
    await flushPromises()

    const refundBtn = wrapper.find('.refund-btn')
    expect(refundBtn.exists()).toBe(true)
    await refundBtn.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('充值订单退款')
    expect(wrapper.text()).toContain('退款扣回说明')

    const input = wrapper.find('.refund-reason-input')
    await input.setValue('协商退款')

    // Find and click confirm button in modal
    const confirmBtn = wrapper.findAll('button').find(b => b.text().includes('确认退款并扣款'))
    expect(confirmBtn).toBeDefined()
    await confirmBtn?.trigger('click')
    await flushPromises()

    expect(refundSpy).toHaveBeenCalledWith('REC20261106_002', { reason: '协商退款' })
  })

  it('hides refund button for non-super-admin users', async () => {
    vi.spyOn(api, 'rechargeOrders').mockResolvedValue({
      data: {
        items: [mockOrders[1]], // paid order
        pagination: { total: 1, page: 1, page_size: 20, pages: 1 },
      },
    } as never)

    const pinia = createPinia()
    const auth = useAuthStore(pinia)
    auth.user = { id: 10, username: 'creator10', is_super_admin: false } as never

    const wrapper = mountPage(pinia)
    await flushPromises()

    expect(wrapper.find('.refund-btn').exists()).toBe(false)
  })

  it('handles empty results or missing pagination gracefully without crashing', async () => {
    vi.spyOn(api, 'rechargeOrders').mockResolvedValue({
      data: {
        items: [],
        pagination: null as never,
      },
    } as never)

    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('暂无符合条件的充值订单')
  })
})


it.each(['light', 'dark'])('keeps a pending refund visible until provider confirmation (%s)', async theme => {
  document.documentElement.dataset.appTheme = theme
  const pinia = createPinia()
  const auth = useAuthStore(pinia)
  auth.user = { id: 1, username: 'admin', is_super_admin: true, nickname: 'Admin' } as never
  vi.spyOn(api, 'rechargeOrders').mockResolvedValue({ data: { items: [{ ...mockOrders[1], status: 'refunding' }], pagination: { total: 1 } } } as never)
  const wrapper = mountPage(pinia)
  await flushPromises()
  expect(wrapper.find('.status-badge').text()).toBe('退款处理中')
  expect(wrapper.find('.refund-btn').exists()).toBe(true)
  vi.spyOn(api, 'refundRechargeOrder').mockResolvedValue({ data: { ...mockOrders[1], status: 'refunding' } } as never)
  await wrapper.find('.refund-btn').trigger('click')
  await wrapper.findAll('button').find(button => button.text().includes('确认退款并扣款'))!.trigger('click')
  await flushPromises()
  expect(wrapper.find('.refund-modal-card').exists()).toBe(false)
  expect(wrapper.find('.status-badge').text()).toBe('退款处理中')
  wrapper.unmount()
})
