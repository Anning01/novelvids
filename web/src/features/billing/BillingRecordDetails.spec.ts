import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import BillingRecordDetails from './BillingRecordDetails.vue'
import type { BillingRecord } from '@/types'

vi.mock('@/api', () => ({ api: { billingRecordDetails: vi.fn() }, statusLabel: () => '已完成' }))
beforeEach(() => vi.resetAllMocks())
const row: BillingRecord = { id: 1, novel_id: 1, task_type: 7, billing_type: 'text', model: '测试模型',
  cost: 0.1, currency: 'CNY', usage: { input_tokens: 10 }, status: 3, created_at: '', updated_at: '' }
const response = (items: BillingRecord[], page = 1) => ({ code: 0, message: '', data: {
  items, pagination: { total: 21, page, page_size: 20, pages: 2 },
} })

it('pages original records and allows retry without closing the conversation row', async () => {
  vi.mocked(api.billingRecordDetails).mockRejectedValueOnce(new Error('暂时无法读取'))
    .mockResolvedValueOnce(response([row])).mockResolvedValueOnce(response([{ ...row, model: '下一页模型' }], 2))
  const wrapper = mount(BillingRecordDetails, { props: { recordId: 1, novelId: 1, showSource: false } })
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('暂时无法读取')
  await wrapper.findAll('button').find(button => button.text() === '重试')!.trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('测试模型')
  await wrapper.findAll('button').find(button => button.text() === '下一页明细')!.trigger('click')
  await flushPromises()
  expect(api.billingRecordDetails).toHaveBeenLastCalledWith(1, { novel_id: 1, page: 2, page_size: 20 })
  expect(wrapper.text()).toContain('下一页模型')
  wrapper.unmount()
})

it('ignores stale details after switching to another conversation', async () => {
  let resolveOld!: (value: ReturnType<typeof response>) => void
  vi.mocked(api.billingRecordDetails).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    .mockResolvedValueOnce(response([{ ...row, model: '当前会话模型' }]))
  const wrapper = mount(BillingRecordDetails, { props: { recordId: 1, novelId: 1, showSource: false } })
  await wrapper.setProps({ recordId: 2 })
  await flushPromises()
  resolveOld(response([{ ...row, model: '旧会话模型' }]))
  await flushPromises()
  expect(wrapper.text()).toContain('当前会话模型')
  expect(wrapper.text()).not.toContain('旧会话模型')
  wrapper.unmount()
})
