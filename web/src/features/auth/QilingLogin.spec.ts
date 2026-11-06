import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import QilingLogin from './QilingLogin.vue'

const user = { id: 1, username: 'user', nickname: '', avatar_url: '', is_super_admin: false }
const session = { token: 'local-session', user }
const qr = 'data:image/png;base64,example'

const { toDataURL } = vi.hoisted(() => ({ toDataURL: vi.fn<() => Promise<string>>() }))
vi.mock('qrcode', () => ({ toDataURL }))

beforeEach(() => {
  vi.useFakeTimers()
  toDataURL.mockResolvedValue(qr)
  vi.spyOn(api, 'qilingStart').mockResolvedValue({
    code: 0, message: '', data: { attempt: 'one-time', authorization_url: 'https://wx.example.test/authorize', expires_in: 30 },
  })
})
afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

it.each(['light', 'dark'])('waits for confirmation before accepting a session in %s mode', async theme => {
  const poll = vi.spyOn(api, 'qilingPoll')
    .mockResolvedValueOnce({ code: 0, message: '', data: { status: 'pending' } })
    .mockResolvedValueOnce({ code: 0, message: '', data: { status: 'completed', session } })
  const wrapper = mount(QilingLogin, { attrs: { 'data-app-theme': theme }, global: { plugins: [createPinia()] } })
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(wrapper.get('[role="status"]').text()).toContain('使用微信扫码')
  expect(wrapper.get('img[alt="器灵登录二维码"]').attributes('src')).toBe(qr)
  expect(toDataURL).toHaveBeenCalledWith('https://wx.example.test/authorize', { width: 224, margin: 4 })
  expect(wrapper.get('a').attributes('href')).toBe('https://wx.example.test/authorize')
  await vi.advanceTimersByTimeAsync(3000)
  expect(wrapper.emitted('authenticated')).toBeUndefined()
  await vi.advanceTimersByTimeAsync(3000)
  expect(wrapper.emitted('authenticated')).toEqual([[session]])
  expect(poll).toHaveBeenCalledTimes(2)
  expect(wrapper.find('img').exists()).toBe(false)
})

it('ignores a pending response after the user cancels', async () => {
  let finish!: (value: Awaited<ReturnType<typeof api.qilingPoll>>) => void
  const poll = vi.spyOn(api, 'qilingPoll').mockReturnValue(new Promise(resolve => { finish = resolve }))
  const wrapper = mount(QilingLogin, { global: { plugins: [createPinia()] } })
  await wrapper.get('button').trigger('click')
  await flushPromises()
  await vi.advanceTimersByTimeAsync(3000)
  await wrapper.get('button').trigger('click')
  expect(poll.mock.calls[0]?.[2].aborted).toBe(true)
  finish({ code: 0, message: '', data: { status: 'completed', session } })
  await flushPromises()
  expect(wrapper.emitted('authenticated')).toBeUndefined()
})

it.each(['clock', 'provider'])('keeps the blurred QR in place after %s expiry and refreshes on click', async source => {
  const start = vi.mocked(api.qilingStart)
  start.mockResolvedValueOnce({ code: 0, message: '', data: { attempt: 'first', authorization_url: 'https://wx.example.test/first', expires_in: 5 } })
  toDataURL.mockResolvedValueOnce(qr).mockResolvedValueOnce('data:image/png;base64,new-code')
  const poll = vi.spyOn(api, 'qilingPoll').mockResolvedValue({ code: 0, message: '', data: { status: source === 'clock' ? 'pending' : 'expired' } })
  const wrapper = mount(QilingLogin, { global: { plugins: [createPinia()] } })
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(wrapper.get('[role="timer"]').text()).toBe('0:05')
  await vi.advanceTimersByTimeAsync(1000)
  expect(wrapper.get('[role="timer"]').text()).toBe('0:04')
  await vi.advanceTimersByTimeAsync(source === 'clock' ? 4000 : 2000)
  expect(wrapper.get('[role="status"]').text()).toBe('二维码已过期')
  expect(wrapper.get('.qiling-login__code').classes()).toContain('is-expired')
  expect(wrapper.get('img').attributes('src')).toBe(qr)
  expect(wrapper.find('a').exists()).toBe(false)
  await vi.advanceTimersByTimeAsync(4000)
  expect(poll).toHaveBeenCalledTimes(1)
  expect(wrapper.emitted('authenticated')).toBeUndefined()
  await wrapper.get('.qiling-login__refresh').trigger('click')
  await flushPromises()
  expect(start).toHaveBeenCalledTimes(2)
  expect(wrapper.get('img').attributes('src')).toBe('data:image/png;base64,new-code')
  expect(wrapper.get('.qiling-login__code').classes()).not.toContain('is-expired')
  expect(wrapper.get('[role="timer"]').text()).toBe('0:30')
})

it('keeps the authorization link and polling available when the QR cannot be rendered', async () => {
  toDataURL.mockRejectedValueOnce(new Error('render failed'))
  vi.spyOn(api, 'qilingPoll').mockResolvedValue({ code: 0, message: '', data: { status: 'completed', session } })
  const wrapper = mount(QilingLogin, { global: { plugins: [createPinia()] } })
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(wrapper.get('[role="status"]').text()).toContain('无法显示二维码')
  expect(wrapper.get('a').attributes('href')).toBe('https://wx.example.test/authorize')
  await vi.advanceTimersByTimeAsync(3000)
  expect(wrapper.emitted('authenticated')).toEqual([[session]])
})
