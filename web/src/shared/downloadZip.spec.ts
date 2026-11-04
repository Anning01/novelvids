/// <reference types="node" />
import { afterEach, expect, it, vi } from 'vitest'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { downloadVideoZip, writeVideoZip } from './downloadZip'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); delete (window as Window & { showSaveFilePicker?: unknown }).showSaveFilePicker })
function memoryOutput() {
  const chunks: Uint8Array[] = []
  return { chunks, write: vi.fn(async (chunk: Uint8Array) => { chunks.push(new Uint8Array(chunk)) }), close: vi.fn(async () => {}), abort: vi.fn(async () => {}) }
}

it('streams unchanged OSS bytes into a valid UTF-8 ZIP in the requested order, with no API or auth requests', async () => {
  const first = new TextEncoder().encode('first MP4 original bytes')
  const second = new Uint8Array([0, 255, 1, 3, 0, 71])
  const fetchMock = vi.fn().mockResolvedValueOnce(new Response(first)).mockResolvedValueOnce(new Response(second))
  vi.stubGlobal('fetch', fetchMock)
  const output = memoryOutput(), progress = vi.fn()
  await writeVideoZip([{ url: 'https://oss.example/one.mp4', filename: '001-分镜1.mp4' },
    { url: 'https://oss.example/two.mp4', filename: '003-分镜3.mp4' }], output, { onProgress: progress })
  expect(fetchMock.mock.calls.map(call => call[0])).toEqual(['https://oss.example/one.mp4', 'https://oss.example/two.mp4'])
  expect(fetchMock.mock.calls.every(call => call[1].credentials === 'omit' && !call[1].headers)).toBe(true)
  expect(output.close).toHaveBeenCalledTimes(1)
  expect(output.abort).not.toHaveBeenCalled()
  expect(progress.mock.calls).toEqual([[1, 2], [2, 2]])
  const dir = mkdtempSync(join(tmpdir(), 'novelvids-zip-test-'))
  try {
    writeFileSync(join(dir, 'shots.zip'), Buffer.concat(output.chunks))
    const result = JSON.parse(execFileSync('python3', ['-c',
      'import zipfile,json,sys; z=zipfile.ZipFile(sys.argv[1]); assert z.testzip() is None; print(json.dumps({"names":z.namelist(),"files":[list(z.read(n)) for n in z.namelist()],"methods":[i.compress_type for i in z.infolist()]}))', join(dir, 'shots.zip')], { encoding: 'utf8' }))
    expect(result.names).toEqual(['001-分镜1.mp4', '003-分镜3.mp4'])
    expect(result.files).toEqual([[...first], [...second]])
    expect(result.methods).toEqual([0, 0])
  } finally { rmSync(dir, { recursive: true, force: true }) }
})

it.each(['network', 'http', 'json', 'empty'])('aborts a partial ZIP rather than silently omitting a failed shot (%s)', async kind => {
  const fetchMock = kind === 'network' ? vi.fn().mockRejectedValue(new TypeError('Failed to fetch')) : vi.fn().mockResolvedValue(
    kind === 'http' ? new Response('denied', { status: 403 }) : kind === 'json'
      ? new Response('{"code":401}', { headers: { 'Content-Type': 'application/json' } }) : new Response(new Uint8Array()),
  )
  vi.stubGlobal('fetch', fetchMock)
  const output = memoryOutput()
  await expect(writeVideoZip([{ url: 'https://oss.example/one.mp4', filename: '001.mp4' }], output)).rejects.toThrow()
  expect(output.close).not.toHaveBeenCalled()
  expect(output.abort).toHaveBeenCalledTimes(1)
})

it('cancels in-flight reads and never fetches the following video', async () => {
  const controller = new AbortController()
  const cancel = vi.fn()
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => new Response(new ReadableStream({
    start(stream) { stream.enqueue(new Uint8Array([1])); controller.abort() }, cancel,
  }))))
  const output = memoryOutput()
  await expect(writeVideoZip([{ url: '/one.mp4', filename: '001.mp4' }, { url: '/two.mp4', filename: '002.mp4' }], output,
    { signal: controller.signal })).rejects.toMatchObject({ name: 'AbortError' })
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(cancel).toHaveBeenCalled()
  expect(output.abort).toHaveBeenCalledTimes(1)
})

it('uses the browser file writer when available, keeping full video blobs out of JavaScript memory', async () => {
  const output = memoryOutput()
  const picker = vi.fn().mockResolvedValue({ createWritable: async () => output })
  Object.assign(window, { showSaveFilePicker: picker })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(new Uint8Array([1, 2]))))
  await downloadVideoZip([{ url: 'https://oss.example/one.mp4', filename: '001.mp4' }], 'episode.zip')
  expect(picker).toHaveBeenCalledWith(expect.objectContaining({ suggestedName: 'episode.zip' }))
  expect(output.close).toHaveBeenCalledTimes(1)
})

it('does not start downloads when the save picker is canceled', async () => {
  Object.assign(window, { showSaveFilePicker: vi.fn().mockRejectedValue(new DOMException('Canceled', 'AbortError')) })
  vi.stubGlobal('fetch', vi.fn())
  await expect(downloadVideoZip([{ url: '/one.mp4', filename: '001.mp4' }], 'episode.zip')).rejects.toMatchObject({ name: 'AbortError' })
  expect(fetch).not.toHaveBeenCalled()
})

it('downloads a browser Blob when native disk streaming is unavailable', async () => {
  vi.useFakeTimers()
  Object.assign(window, { showSaveFilePicker: vi.fn().mockRejectedValue(new DOMException('Not supported here', 'SecurityError')) })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(new Uint8Array([1, 2, 3]))))
  const create = vi.fn().mockReturnValue('blob:zip-result'), revoke = vi.fn()
  vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: revoke })
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  try {
    await downloadVideoZip([{ url: 'https://oss.example/one.mp4', filename: '001.mp4' }], 'episode.zip')
    expect(create.mock.calls[0]![0].size).toBeGreaterThan(30)
    expect(create.mock.calls[0]![0].type).toBe('application/zip')
    expect(click).toHaveBeenCalledTimes(1)
    expect(revoke).not.toHaveBeenCalled()
    vi.advanceTimersByTime(60_000)
    expect(revoke).toHaveBeenCalledWith('blob:zip-result')
  } finally { vi.useRealTimers() }
})

it('rejects unsafe file paths before making a media request', async () => {
  vi.stubGlobal('fetch', vi.fn())
  const output = memoryOutput()
  await expect(writeVideoZip([{ url: '/one.mp4', filename: '../escape.mp4' }], output)).rejects.toThrow('名称无效')
  expect(fetch).not.toHaveBeenCalled()
  expect(output.abort).toHaveBeenCalledTimes(1)
})
