import { spawnSync } from 'node:child_process'
import { Blob as NativeBlob } from 'node:buffer'
import { webcrypto } from 'node:crypto'
import { afterEach, expect, it, vi } from 'vitest'
import { ProjectZip } from './projectZip'

afterEach(() => vi.unstubAllGlobals())

it('writes readable ZIP64 media, checked in blocks, and a versioned manifest', async () => {
  vi.stubGlobal('Blob', NativeBlob)
  vi.stubGlobal('crypto', webcrypto)
  const zip = new ProjectZip()
  const bytes = new Uint8Array(8 * 1024 * 1024 + 12)
  bytes.fill(7)
  const signal = new AbortController().signal
  const media = await zip.add('media/1.mp4', new Blob([bytes]), signal)
  await zip.add('project.json', new Blob([JSON.stringify({format:'novelvids.project',version:2,project:{},media:[media]})]), signal)
  const verify = spawnSync('python3', ['-c', [
    'import io, sys, zipfile, json, hashlib',
    'z=zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read()))',
    'assert z.testzip() is None',
    'e=json.loads(z.read("project.json"))["media"][0]',
    'b=z.read(e["member"]); size=8*1024*1024',
    'assert len(b)==e["byte_length"]==size+12 and b[-1]==7',
    'assert hashlib.sha256(b"".join(hashlib.sha256(b[i:i+size]).digest() for i in range(0,len(b),size))).hexdigest()==e["sha256"]',
  ].join('\n')], {input:Buffer.from(await zip.finish().arrayBuffer())})
  expect(verify.status, verify.stderr.toString()).toBe(0)
})
