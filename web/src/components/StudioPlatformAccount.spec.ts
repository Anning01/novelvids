import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import StudioPlatformAccount from './StudioPlatformAccount.vue'

vi.mock('@/api', () => ({ api: { studioPlatformAccount: vi.fn() } }))
beforeEach(() => vi.resetAllMocks())

it('discards a balance response for the previous key after replacement', async () => {
  let finishOld!: (value: Awaited<ReturnType<typeof api.studioPlatformAccount>>) => void
  const balance = (team: number) => ({ code: 0, message: '', data: {
    balance: String(team), currency: 'CNY', recharge_url: `https://platform.example/#/profile?recharge=1&team=${team}`,
  } })
  vi.mocked(api.studioPlatformAccount).mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
    .mockResolvedValueOnce(balance(2))
  const wrapper = mount(StudioPlatformAccount, { props: { accountRevision: 0 } })
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === '查看平台余额')!.trigger('click')
  await wrapper.setProps({ accountRevision: 1 })
  await flushPromises()
  finishOld(balance(1))
  await flushPromises()
  expect(wrapper.get('a').attributes('href')).toContain('team=2')
  expect(wrapper.text()).not.toContain('1 CNY')
  wrapper.unmount()
})
