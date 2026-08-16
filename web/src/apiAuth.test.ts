import { afterEach, expect, it, vi } from 'vitest'
import { api, clearAuthToken, getAuthToken, setAuthToken } from './api'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  localStorage.clear()
})

it('attaches bearer token when logged in', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    code: 0, message: 'ok', data: { enabled: true },
  }), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  setAuthToken('secret-token')
  await api.authStatus()

  expect(fetchMock).toHaveBeenCalledWith('/api/auth/status', {
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer secret-token' },
  })
})

it('omits authorization header when logged out', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    code: 0, message: 'ok', data: { enabled: false },
  }), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  await api.authStatus()

  expect(fetchMock).toHaveBeenCalledWith('/api/auth/status', {
    headers: { 'Content-Type': 'application/json' },
  })
})

it('clears token and redirects to login on 401', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    code: 401, message: '登录已失效，请重新登录', data: null,
  }), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  setAuthToken('stale-token')
  await expect(api.me()).rejects.toThrow('登录已失效')
  expect(getAuthToken()).toBeNull()
  expect(window.location.hash).toBe('#/login')
})

it('does not redirect when login itself returns 401', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    code: 401, message: '用户名或密码错误', data: null,
  }), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  window.location.hash = '#/projects'
  await expect(api.login('alice', 'wrong')).rejects.toThrow('用户名或密码错误')
  expect(window.location.hash).toBe('#/projects')
  expect(clearAuthToken()).toBeUndefined()
})
