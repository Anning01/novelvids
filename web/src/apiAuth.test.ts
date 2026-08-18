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
  // 第一次调用是直传策略探测（返回 direct:false → 走本地上传）
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({
      code: 0, message: 'ok', data: { direct: false },
    }), { status: 200 }))
    .mockResolvedValue(new Response(JSON.stringify({
      code: 0, message: 'ok',
      data: { total: 1, files: [{ filename: 'a.txt', original_filename: 'a.txt', content_type: 'text/plain', file_path: '/media/a.txt', text_content: '', chapter_validation: null, message: 'ok' }] },
    }), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  setAuthToken('up-token')
  localStorage.setItem('novelvids_active_team', '7')

  const file = new File(['hello'], 'a.txt', { type: 'text/plain' })
  await api.upload(file)

  const [url, options] = fetchMock.mock.calls[1]
  expect(url).toBe('/api/file/upload')
  expect(options.headers.Authorization).toBe('Bearer up-token')
  expect(options.headers['X-Team-Id']).toBe('7')
  // FormData 上传不应设置 JSON Content-Type（交给浏览器自动带 boundary）
  expect(options.headers['Content-Type']).toBeUndefined()
})

it('直传 OSS：先取策略，再直传对象存储，最后服务端终局', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({
      code: 0, message: 'ok',
      data: {
        direct: true, provider: 'aliyun', key: 'uploads/0/20260818/abc.txt',
        upload_url: 'https://oss.example.com/bucket',
        fields: { key: 'uploads/0/20260818/abc.txt', policy: 'p', signature: 's', OSSAccessKeyId: 'ak' },
      },
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response('', { status: 200 })) // OSS 直传成功
    .mockResolvedValueOnce(new Response(JSON.stringify({
      code: 0, message: 'ok',
      data: { filename: '剧本.txt', url: 'https://cdn.example.com/uploads/0/20260818/abc.txt', key: 'uploads/0/20260818/abc.txt', text_content: '第一章 开端', chapter_validation: { valid: true, chapter_count: 1, text_length: 7, message: 'ok' } },
    }), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)

  const file = new File(['第一章 开端'], '剧本.txt', { type: 'text/plain' })
  const uploaded = await api.upload(file)

  expect(fetchMock.mock.calls[1][0]).toBe('https://oss.example.com/bucket')
  expect(uploaded.url).toBe('https://cdn.example.com/uploads/0/20260818/abc.txt')
  expect(uploaded.text_content).toBe('第一章 开端')
  expect(uploaded.chapter_validation?.valid).toBe(true)
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
