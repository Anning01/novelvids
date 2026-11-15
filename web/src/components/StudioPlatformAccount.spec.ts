import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import StudioPlatformAccount from './StudioPlatformAccount.vue'

vi.mock('@/api', () => ({ api: { studioPlatformAccount: vi.fn() } }))
beforeEach(() => vi.resetAllMocks())

const balance = (value: number) => ({ code: 0, message: '', data: {
  balance: String(value), currency: 'CNY', recharge_url: `https://platform.example/#/profile?recharge=1&team=${value}`,
} })

it('loads and displays the balance immediately without a second query click', async () => {
  let finish!: (value: Awaited<ReturnType<typeof api.studioPlatformAccount>>) => void
  vi.mocked(api.studioPlatformAccount).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  const wrapper = mount(StudioPlatformAccount)
  expect(api.studioPlatformAccount).toHaveBeenCalledOnce()
  await wrapper.vm.$nextTick()
  expect(wrapper.find('[role="status"]').exists()).toBe(true)
  expect(wrapper.text()).not.toContain('查看平台余额')
  finish(balance(12))
  await flushPromises()
  expect(wrapper.text()).toContain('12 CNY')
  wrapper.unmount()
})

it('offers retry after a failed automatic query', async () => {
  vi.mocked(api.studioPlatformAccount).mockRejectedValueOnce(new Error('连接失败')).mockResolvedValueOnce(balance(8))
  const wrapper = mount(StudioPlatformAccount)
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('连接失败')
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('8 CNY')
  expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  wrapper.unmount()
})

it('discards a balance response for the previous key after replacement', async () => {
  let finishOld!: (value: Awaited<ReturnType<typeof api.studioPlatformAccount>>) => void
  vi.mocked(api.studioPlatformAccount).mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
    .mockResolvedValueOnce(balance(2))
  const wrapper = mount(StudioPlatformAccount, { props: { accountRevision: 0 } })
  await flushPromises()
  await wrapper.setProps({ accountRevision: 1 })
  await flushPromises()
  finishOld(balance(1))
  await flushPromises()
  expect(wrapper.get('a').attributes('href')).toContain('team=2')
  expect(wrapper.text()).not.toContain('1 CNY')
  wrapper.unmount()
})
