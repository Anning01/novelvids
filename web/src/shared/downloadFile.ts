export async function downloadFile(url: string, filename: string) {
  const response = await fetch(url)
  if (!response.ok) throw new Error('文件下载失败，请稍后重试')
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
