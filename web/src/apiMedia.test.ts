import { afterEach, describe, expect, it, vi } from 'vitest'
import { mediaUrl } from './api'

afterEach(() => {
  vi.unstubAllEnvs()
})

describe('mediaUrl（分离部署地址解析）', () => {
  it('未配置 VITE_API_BASE 时保持同源相对路径', () => {
    vi.stubEnv('VITE_API_BASE', '')
    expect(mediaUrl('/media/abc.png')).toBe('/media/abc.png')
    expect(mediaUrl('https://cdn.example.com/x.png')).toBe('https://cdn.example.com/x.png')
    expect(mediaUrl('')).toBe('')
    expect(mediaUrl(null)).toBe('')
  })

  it('配置 VITE_API_BASE 时把 /media 相对路径前缀为后端域名', () => {
    vi.stubEnv('VITE_API_BASE', 'https://api.example.com')
    expect(mediaUrl('/media/abc.png')).toBe('https://api.example.com/media/abc.png')
    // 非 /media 路径不受影响
    expect(mediaUrl('/other')).toBe('/other')
    // 绝对地址原样返回
    expect(mediaUrl('https://cdn.example.com/x.png')).toBe('https://cdn.example.com/x.png')
  })

  it('容忍 VITE_API_BASE 末尾斜杠', () => {
    vi.stubEnv('VITE_API_BASE', 'https://api.example.com/')
    expect(mediaUrl('/media/abc.png')).toBe('https://api.example.com/media/abc.png')
  })
})
