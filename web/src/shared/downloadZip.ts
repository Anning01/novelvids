import { tr } from '@/i18n'

export interface ZipDownloadFile { url: string; filename: string }
interface ZipOutput {
  write(chunk: Uint8Array): Promise<unknown>
  close(): Promise<unknown>
  abort(): Promise<unknown>
}
interface DownloadWindow extends Window {
  showSaveFilePicker?: (options: { suggestedName: string; types: Array<{ description: string; accept: Record<string, string[]> }> }) => Promise<{ createWritable(): Promise<ZipOutput> }>
}
const ZIP32_MAX = 0xffff_ffff
const encoder = new TextEncoder()
const crcTable = Uint32Array.from({ length: 256 }, (_, value) => {
  for (let i = 0; i < 8; i++) value = value & 1 ? 0xedb8_8320 ^ value >>> 1 : value >>> 1
  return value >>> 0
})

function header(size: number, fields: Array<[number, number, 2 | 4]>) {
  const bytes = new Uint8Array(size)
  const view = new DataView(bytes.buffer)
  for (const [offset, value, length] of fields) {
    if (length === 2) view.setUint16(offset, value, true)
    else view.setUint32(offset, value, true)
  }
  return bytes
}

/** MP4 files are already compressed. ZIP stores them unchanged, one download at a time. */
export async function writeVideoZip(files: readonly ZipDownloadFile[], output: ZipOutput,
  options: { signal?: AbortSignal; onProgress?: (completed: number, total: number) => void } = {}) {
  let offset = 0
  const directory: Uint8Array[] = []
  const names = new Set<string>()
  const date = new Date()
  const time = date.getHours() << 11 | date.getMinutes() << 5 | date.getSeconds() >>> 1
  const day = Math.max(0, date.getFullYear() - 1980) << 9 | (date.getMonth() + 1) << 5 | date.getDate()
  async function write(bytes: Uint8Array) {
    options.signal?.throwIfAborted()
    // shortcut: ZIP32 supports archives under 4 GiB; use ZIP64 when larger exports are needed.
    if (offset + bytes.byteLength > ZIP32_MAX) throw new Error(tr('压缩包超过 4GB，请分批下载分镜'))
    await output.write(bytes)
    offset += bytes.byteLength
  }
  try {
    if (!files.length || files.length > 65535) throw new Error(tr('可打包的视频数量无效'))
    for (const [index, file] of files.entries()) {
      options.signal?.throwIfAborted()
      if (!file.filename || /[\x00-\x1f/\\]/u.test(file.filename) || names.has(file.filename)) throw new Error(tr('压缩包内的视频名称无效或重复'))
      names.add(file.filename)
      const name = encoder.encode(file.filename)
      if (name.length > 65535) throw new Error(tr('视频名称过长'))
      const start = offset
      const flags = 0x808 // UTF-8 names and streaming size/CRC descriptor.
      await write(header(30, [[0, 0x04034b50, 4], [4, 20, 2], [6, flags, 2], [10, time, 2], [12, day, 2], [26, name.length, 2]]))
      await write(name)
      const response = await fetch(file.url, { credentials: 'omit', signal: options.signal })
      if (!response.ok || !response.body || response.headers.get('content-type')?.includes('application/json')) throw new Error(tr('读取分镜视频失败：{p0}', { p0: file.filename }))
      const reader = response.body.getReader()
      let crc = 0xffff_ffff
      let size = 0
      let complete = false
      try {
        while (true) {
          options.signal?.throwIfAborted()
          const { value, done } = await reader.read()
          if (done) { complete = true; break }
          size += value.byteLength
          for (const byte of value) crc = crcTable[(crc ^ byte) & 0xff]! ^ crc >>> 8
          await write(value)
        }
      } finally {
        if (!complete) await reader.cancel().catch(() => undefined)
        reader.releaseLock()
      }
      if (!size) throw new Error(tr('分镜视频文件为空：{p0}', { p0: file.filename }))
      crc = (crc ^ 0xffff_ffff) >>> 0
      await write(header(16, [[0, 0x08074b50, 4], [4, crc, 4], [8, size, 4], [12, size, 4]]))
      directory.push(header(46, [[0, 0x02014b50, 4], [4, 20, 2], [6, 20, 2], [8, flags, 2],
        [12, time, 2], [14, day, 2], [16, crc, 4], [20, size, 4], [24, size, 4], [28, name.length, 2], [42, start, 4]]), name)
      options.onProgress?.(index + 1, files.length)
    }
    const start = offset
    for (const entry of directory) await write(entry)
    const size = offset - start
    await write(header(22, [[0, 0x06054b50, 4], [8, files.length, 2], [10, files.length, 2], [12, size, 4], [16, start, 4]]))
    await output.close()
  } catch (error) {
    await output.abort().catch(() => undefined)
    throw error
  }
}

export async function downloadVideoZip(files: readonly ZipDownloadFile[], filename: string,
  options: { signal?: AbortSignal; onProgress?: (completed: number, total: number) => void } = {}) {
  const picker = (window as DownloadWindow).showSaveFilePicker
  if (picker) {
    let file
    try {
      file = await picker.call(window, { suggestedName: filename, types: [{ description: 'ZIP', accept: { 'application/zip': ['.zip'] } }] })
    } catch (error) {
      if (!(error instanceof DOMException) || !['SecurityError', 'NotSupportedError'].includes(error.name)) throw error
    }
    if (file) {
      await writeVideoZip(files, await file.createWritable(), options)
      return
    }
  }
  const chunks: Uint8Array<ArrayBuffer>[] = []
  let blob: Blob | null = null
  await writeVideoZip(files, {
    async write(chunk) { chunks.push(new Uint8Array(chunk)) },
    async close() { blob = new Blob(chunks, { type: 'application/zip' }); chunks.length = 0 },
    async abort() { chunks.length = 0 },
  }, options)
  options.signal?.throwIfAborted()
  const url = URL.createObjectURL(blob!)
  const link = document.createElement('a')
  link.href = url; link.download = filename
  document.body.appendChild(link)
  try { link.click() } finally {
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  }
}
