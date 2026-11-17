import type { SkillFile, SkillPackageLimits } from './skillsApi'
import { tr } from '@/i18n'

export interface SkillFileNode { name: string; path: string; directory: boolean; children: SkillFileNode[] }
export function skillFileTree(files: SkillFile[]): SkillFileNode[] {
  const root: SkillFileNode = { name: '', path: '', directory: true, children: [] }
  for (const file of files) {
    let node = root
    const parts = file.path.split('/')
    for (const [index, name] of parts.entries()) {
      const path = parts.slice(0, index + 1).join('/')
      let child = node.children.find(item => item.path === path)
      if (!child) { child = { name, path, directory: index !== parts.length - 1, children: [] }; node.children.push(child) }
      node = child
    }
  }
  const sort = (nodes: SkillFileNode[]): SkillFileNode[] => [...nodes].sort((a, b) =>
    Number(b.name === 'SKILL.md') - Number(a.name === 'SKILL.md') || Number(b.directory) - Number(a.directory) || a.name.localeCompare(b.name))
    .map(node => ({ ...node, children: sort(node.children) }))
  return sort(root.children)
}
export function validSkillPath(path: string) {
  return !!path && path.length <= 240 && !/[\\\0:]/.test(path) && path.split('/').every(part => !!part && part !== '.' && part !== '..')
}
export function uniqueSkillPaths(paths: string[]) {
  const names = new Map<string, string>()
  const files = new Set(paths)
  if (files.size !== paths.length) return false
  for (const path of paths) {
    if (!validSkillPath(path)) return false
    const parts = path.split('/')
    for (let index = 1; index <= parts.length; index++) {
      const node = parts.slice(0, index).join('/')
      const identity = node.normalize('NFC').toLowerCase()
      if (names.has(identity) && names.get(identity) !== node) return false
      if (index < parts.length && files.has(node)) return false
      names.set(identity, node)
    }
  }
  return true
}
export function skillFileSize(file: SkillFile) {
  return file.encoding === 'utf-8' ? new TextEncoder().encode(file.content).length
    : file.content.length * 3 / 4 - (file.content.endsWith('==') ? 2 : file.content.endsWith('=') ? 1 : 0)
}
export function skillFileBlob(file: SkillFile): Blob {
  if (file.encoding === 'utf-8') return new Blob([file.content], { type: 'text/plain;charset=utf-8' })
  const bytes = Uint8Array.from(atob(file.content), char => char.charCodeAt(0))
  return new Blob([bytes], { type: imageMime(file.path) ?? 'application/octet-stream' })
}
export function imageMime(path: string) {
  const extension = path.split('.').pop()?.toLowerCase() ?? ''
  return ({ png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif', webp: 'image/webp', avif: 'image/avif' } as Record<string, string>)[extension]
}
export async function browserSkillFile(file: File, path: string, limits: SkillPackageLimits): Promise<SkillFile> {
  if (file.size > limits.max_file_bytes) throw new Error(tr('文件超过允许大小：{p0}', { p0: file.name }))
  const bytes = new Uint8Array(await file.arrayBuffer())
  try {
    const content = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes)
    if (content.includes('\0')) throw new Error('binary')
    return { path, encoding: 'utf-8', content }
  } catch {
    let binary = ''
    for (let index = 0; index < bytes.length; index += 32768) binary += String.fromCharCode(...bytes.subarray(index, index + 32768))
    return { path, encoding: 'base64', content: btoa(binary) }
  }
}
export function sameSkillFiles(left: SkillFile[], right: SkillFile[]) {
  if (left.length !== right.length) return false
  const original = new Map(right.map(file => [file.path, file]))
  return left.every(file => {
    const before = original.get(file.path)
    return before && file.content === before.content && file.encoding === before.encoding && !!file.executable === !!before.executable
  })
}
