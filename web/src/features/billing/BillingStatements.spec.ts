import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import { setLocale } from '@/i18n'
import AppSelect from '@/components/AppSelect.vue'
import AppPagination from '@/components/AppPagination.vue'
import BillingStatements from './BillingStatements.vue'
import type { BillingStatement } from '@/types'

vi.mock('@/api', async original => ({ ...await original<typeof import('@/api')>(), api: {
  billingStatementParties: vi.fn(), billingStatements: vi.fn(), exportBillingStatement: vi.fn(),
} }))
const statement = (): BillingStatement => ({
  snapshot_id: 999,
  summary: { total_cost: '1.234567', total_transactions: 38, team_balance: '8.765433' },
  pagination: { total: 38, page: 1, page_size: 20, pages: 2 },
  items: [{ id: 999, created_at: '2026-01-02 10:00:00', team_id: 10, team_name: '客户团队',
    user_id: 20, user_name: '客户', novel_id: 30, novel_name: '测试项目', usage_record_id: 501,
    billing_type: 'video', task_type: 4, task_status: 3, video_id: 401,
    usage: { seconds: 5, resolution: '480p' }, cost: '0.123456', balance_after: '8.765433' }],
})
beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(api.billingStatementParties).mockResolvedValue({ code: 0, message: '', data: {
    teams: [{ id: 10, name: '客户团队' }], users: [{ id: 20, name: '客户' }],
  } })
  vi.mocked(api.billingStatements).mockResolvedValue({ code: 0, message: '', data: statement() })
  vi.mocked(api.exportBillingStatement).mockResolvedValue(undefined)
})

it.each(['light', 'dark'])('filters and exports all matching rows at exact precision (%s)', async theme => {
  document.documentElement.dataset.appTheme = theme
  const wrapper = mount(BillingStatements)
  await flushPromises()
  expect(wrapper.text()).toContain('¥1.234567')
  expect(wrapper.text()).toContain('¥0.123456')
  const [teams, users] = wrapper.findAllComponents(AppSelect)
  teams!.vm.$emit('update:modelValue', '10')
  users!.vm.$emit('update:modelValue', '20')
  await wrapper.get('input[aria-label="开始日期"]').setValue('2026-11-09')
  await wrapper.get('input[aria-label="结束日期"]').setValue('2026-11-09')
  await flushPromises()
  expect(api.billingStatements).toHaveBeenLastCalledWith({ team_id: 10, user_id: 20,
    start_date: '2026-11-09', end_date: '2026-11-09', snapshot_id: undefined, page: 1, page_size: 20 })
  const exportButton = wrapper.findAll('button').find(b => b.text().includes('导出全部明细'))!
  await exportButton.trigger('click'); await flushPromises()
  expect(api.exportBillingStatement).toHaveBeenCalledWith({ team_id: 10, user_id: 20,
    start_date: '2026-11-09', end_date: '2026-11-09', snapshot_id: 999 })
  wrapper.findComponent(AppPagination).vm.$emit('page-change', 2)
  await flushPromises()
  expect(api.billingStatements).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, snapshot_id: 999 }))
  users!.vm.$emit('update:modelValue', '')
  await flushPromises()
  expect(api.billingStatements).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, snapshot_id: undefined, user_id: undefined }))
})

it('does not let an older response replace the selected team or exported range', async () => {
  let resolveOld!: (value: Awaited<ReturnType<typeof api.billingStatements>>) => void
  vi.mocked(api.billingStatements).mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve }))
  const wrapper = mount(BillingStatements)
  await flushPromises()
  expect(wrapper.find('[role="status"]').exists()).toBe(true)
  wrapper.findComponent(AppSelect).vm.$emit('update:modelValue', '10')
  await flushPromises()
  resolveOld({ code: 0, message: '', data: { ...statement(), summary: { total_cost: '999.000000', total_transactions: 1, team_balance: null } } })
  await flushPromises()
  expect(wrapper.text()).not.toContain('999.000000')
  await wrapper.findAll('button').find(b => b.text().includes('导出全部明细'))!.trigger('click')
  expect(api.exportBillingStatement).toHaveBeenCalledWith(expect.objectContaining({ team_id: 10 }))
})

it('shows empty and failed states, blocks invalid dates and allows retry', async () => {
  vi.mocked(api.billingStatements).mockRejectedValueOnce(new Error('连接中断'))
  const wrapper = mount(BillingStatements)
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('连接中断')
  await wrapper.get('[role="alert"] button').trigger('click')
  await flushPromises()
  await wrapper.get('input[aria-label="开始日期"]').setValue('2026-11-10')
  const count = vi.mocked(api.billingStatements).mock.calls.length
  await wrapper.get('input[aria-label="结束日期"]').setValue('2026-11-09')
  await flushPromises()
  expect(api.billingStatements).toHaveBeenCalledTimes(count)
  expect(wrapper.get('[role="alert"]').text()).toContain('开始日期不能晚于结束日期')
  expect(wrapper.findAll('button').find(b => b.text().includes('导出全部明细'))!.attributes('disabled')).toBeDefined()
  vi.mocked(api.billingStatements).mockResolvedValue({ code: 0, message: '', data: {
    ...statement(), items: [], summary: { total_cost: '0.000000', total_transactions: 0, team_balance: null },
  } })
  await wrapper.get('input[aria-label="结束日期"]').setValue('2026-11-10')
  await flushPromises()
  expect(wrapper.text()).toContain('当前范围暂无扣款记录')
})

it('translates the billing view when language changes', async () => {
  const wrapper = mount(BillingStatements)
  await flushPromises()
  setLocale('en')
  await flushPromises()
  expect(wrapper.text()).toContain('Actual deductions')
  expect(wrapper.text()).toContain('Export all details')
})


it('keeps the full long source name accessible in the compact table without changing exact charges', async () => {
  const longName = '山峰间的云海缓慢流动，镜头跟随人物穿过街道。'.repeat(12)
  vi.mocked(api.billingStatements).mockResolvedValue({code:0,message:'',data:{
    ...statement(),items:[{...statement().items[0]!,novel_name:longName}],
  }})
  const wrapper = mount(BillingStatements,{props:{compact:true}})
  await flushPromises()
  expect(wrapper.get('.statement-project-name').attributes('title')).toBe(longName)
  expect(wrapper.get('.statement-project-name').text()).toBe(longName)
  expect(wrapper.get('.statement-table').text()).toContain('¥0.123456')
  wrapper.unmount()
})
