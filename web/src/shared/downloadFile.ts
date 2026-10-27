
import { tr } from '@/i18n'
export async function downloadFile(url: string, filename: string, headers?: Record<string, string>) {
  const response = await (headers ? fetch(url, { headers }) : fetch(url))
  if (!response.ok) throw new Error(tr('文件下载失败，请稍后重试'))
  // API failures use the shared JSON envelope, including some HTTP 200 responses.
  if (response.headers?.get('content-type')?.includes('application/json')) {
    const payload: unknown = await response.json()
    const message = payload && typeof payload === 'object' && 'message' in payload && typeof payload.message === 'string'
      ? payload.message : tr('文件下载失败，请稍后重试')
    throw new Error(message)
  }
  const blobUrl = URL.createObjectURL(await response.blob())
  try {
    const link = document.createElement('a')
    link.href = blobUrl
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
  } finally {
    URL.revokeObjectURL(blobUrl)
  }
}
