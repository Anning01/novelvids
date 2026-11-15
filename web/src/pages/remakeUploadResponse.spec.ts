import { afterEach, expect, it, vi } from 'vitest'
import { api } from '@/api'

afterEach(() => vi.unstubAllGlobals())

it.each([
  [413, '<html>Request Entity Too Large</html>', '视频超过上传服务的大小限制'],
  [502, '<html>Bad Gateway</html>', '服务暂不可用，请稍后重试'],
  [400, '{"code":400,"message":"视频时长超过限制"}', '视频时长超过限制'],
])('shows a readable upload error for HTTP %i', async (status, responseText, message) => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({code:0,data:{direct:false}})))
  vi.stubGlobal('XMLHttpRequest', class {
    status = status
    responseText = responseText
    upload = {}
    onload = () => {}
    open() {}
    setRequestHeader() {}
    send() { this.onload() }
  })
  await expect(api.uploadRemakeVideo(new File(['video'], 'test.mp4'))).rejects.toThrow(message)
})
