import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { api, ApiRequestError } from '@/api'
import TeamQuotaDialog from './TeamQuotaDialog.vue'

afterEach(() => vi.restoreAllMocks())

it('requires the new balance to be reviewed after a conflict and sends one debit per submission', async () => {
  const balance = (value: string, revision: number) => ({ code: 0, message: '', data: {team_id: 4, balance: value, last_transaction_id: revision} })
  vi.spyOn(api, 'teamBalance').mockResolvedValueOnce(balance('25', 7)).mockResolvedValueOnce(balance('20', 8))
  const debit = vi.spyOn(api, 'teamDeduct').mockRejectedValueOnce(new ApiRequestError('余额已变动', 409, 409)).mockResolvedValueOnce(balance('16.5', 9))
  const wrapper = mount(TeamQuotaDialog, {props: {team: {id: 4, name: '审核队'}}})
  await flushPromises()
  const submit = wrapper.get('button[type="submit"]')
  await wrapper.get('input[inputmode="decimal"]').setValue('26')
  await wrapper.get('input[maxlength]').setValue('回收未使用额度')
  expect(submit.attributes('disabled')).toBeDefined()
  await wrapper.get('input[inputmode="decimal"]').setValue('3.5')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(debit).toHaveBeenCalledTimes(1)
  expect(debit.mock.calls[0]?.[0].last_transaction_id).toBe(7)
  expect(wrapper.get('[role="alert"]').text()).toContain('余额已变动')
  expect(wrapper.text()).toContain('¥ 20')
  expect(wrapper.emitted('saved')).toBeUndefined()
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(debit).toHaveBeenLastCalledWith({team_id: 4, amount: '3.5', note: '回收未使用额度', last_transaction_id: 8})
  expect(wrapper.emitted('saved')).toHaveLength(1)
  wrapper.unmount()
})
