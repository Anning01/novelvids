// Stored ZIP64 records keep original video bytes intact and support projects over 4 GiB.
const encoder = new TextEncoder()
const blockSize = 8 * 1024 * 1024
const crcTable = Uint32Array.from({ length: 256 }, (_, n) => {
  let c = n
  for (let i = 0; i < 8; i++) c = (c >>> 1) ^ ((c & 1) ? 0xedb88320 : 0)
  return c >>> 0
})

class RecordBytes {
  private parts: number[] = []
  u16(value: number) { this.parts.push(value & 255, (value >>> 8) & 255); return this }
  u32(value: number) { return this.u16(value).u16(value >>> 16) }
  u64(value: number) { return this.u32(value).u32(Math.floor(value / 0x100000000)) }
  bytes(value: Uint8Array) { for (const n of value) this.parts.push(n); return this }
  finish() { return Uint8Array.from(this.parts) }
}

async function checksums(file: Blob, signal: AbortSignal) {
  let crc = 0xffffffff
  const blocks = new Uint8Array(Math.ceil(file.size / blockSize) * 32)
  for (let offset = 0, i = 0; offset < file.size; offset += blockSize, i += 32) {
    signal.throwIfAborted()
    const bytes = new Uint8Array(await file.slice(offset, offset + blockSize).arrayBuffer())
    for (const b of bytes) crc = crcTable[(crc ^ b) & 255]! ^ (crc >>> 8)
    blocks.set(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), i)
  }
  const root = new Uint8Array(await crypto.subtle.digest('SHA-256', blocks))
  return { crc: (crc ^ 0xffffffff) >>> 0, sha256: Array.from(root, b => b.toString(16).padStart(2, '0')).join('') }
}

export class ProjectZip {
  private data: BlobPart[] = []
  private central: Uint8Array<ArrayBuffer>[] = []
  private offset = 0

  async add(member: string, file: Blob, signal: AbortSignal) {
    const { crc, sha256 } = await checksums(file, signal)
    const name = encoder.encode(member)
    const common = new RecordBytes().u16(45).u16(0x800).u16(0).u16(0).u16(0x21)
      .u32(crc).u32(0xffffffff).u32(0xffffffff).u16(name.length).finish()
    const sizes = new RecordBytes().u64(file.size).u64(file.size).finish()
    const local = new RecordBytes().u32(0x04034b50).bytes(common).u16(20).bytes(name)
      .u16(1).u16(16).bytes(sizes).finish()
    this.central.push(new RecordBytes().u32(0x02014b50).u16(45).bytes(common).u16(28)
      .u16(0).u16(0).u16(0).u32(0).u32(0xffffffff).bytes(name).u16(1).u16(24)
      .bytes(sizes).u64(this.offset).finish())
    this.data.push(local, file)
    this.offset += local.length + file.size
    return { member, byte_length: file.size, sha256, hash_scheme: 'sha256-blocks-8m' as const }
  }

  finish() {
    const count = this.central.length
    const directorySize = this.central.reduce((total, entry) => total + entry.length, 0)
    const end = new RecordBytes().u32(0x06064b50).u64(44).u16(45).u16(45).u32(0).u32(0)
      .u64(count).u64(count).u64(directorySize).u64(this.offset)
      .u32(0x07064b50).u32(0).u64(this.offset + directorySize).u32(1)
      .u32(0x06054b50).u16(0).u16(0).u16(0xffff).u16(0xffff).u32(0xffffffff).u32(0xffffffff).u16(0)
    return new Blob([...this.data, ...this.central, end.finish()], { type: 'application/zip' })
  }
}
