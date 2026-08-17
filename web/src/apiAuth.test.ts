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


it('attaches bearer token and team header to uploads', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    code: 0, message: 'ok',
    data: { total: 1, files: [{ filename: 'a.txt', original_filename: 'a.txt', content_type: 'text/plain', file_path: '/media/a.txt', text_content: '', chapter_validation: null, message: 'ok' }] },
  }), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  setAuthToken('up-token')
  localStorage.setItem('novelvids_active_team', '7')

  const file = new File(['hello'], 'a.txt', { type: 'text/plain' })
  await api.upload(file)

  const [url, options] = fetchMock.mock.calls[0]
  expect(url).toBe('/api/file/upload')
  expect(options.headers.Authorization).toBe('Bearer up-token')
  expect(options.headers['X-Team-Id']).toBe('7')
  // FormData 上传不应设置 JSON Content-Type（交给浏览器自动带 boundary）
  expect(options.headers['Content-Type']).toBeUndefined()
})

it('redirects to login when upload gets 401', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    code: 401, message: '未登录', data: null,
  }), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  setAuthToken('stale-up-token')
  window.location.hash = '#/projects'
  await expect(api.upload(new File(['x'], 'x.txt'))).rejects.toThrow('未登录')
  expect(getAuthToken()).toBeNull()
  expect(window.location.hash).toBe('#/login')
})
