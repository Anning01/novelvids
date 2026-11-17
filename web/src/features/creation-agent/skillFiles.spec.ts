import { expect, it } from 'vitest'
import { browserSkillFile, sameSkillFiles, skillFileSize, skillFileTree, uniqueSkillPaths, validSkillPath } from './skillFiles'
import { packageLimits } from '@/test/skillPackageFixture'
import type { SkillFile } from './skillsApi'

it('builds a real directory tree with the Skill entry first', () => {
  const files: SkillFile[] = [{ path: 'references/method.md', content: '', encoding: 'utf-8' },
    { path: 'scripts/check.py', content: '', encoding: 'utf-8' }, { path: 'SKILL.md', content: '', encoding: 'utf-8' }]
  const tree = skillFileTree(files)
  expect(tree.map(node => node.path)).toEqual(['SKILL.md', 'references', 'scripts'])
  expect(tree[1]!.children[0]!.path).toBe('references/method.md')
  expect(uniqueSkillPaths(['SKILL.md', 'references/a.md'])).toBe(true)
  expect(uniqueSkillPaths(['a', 'a/b.md'])).toBe(false)
  expect(uniqueSkillPaths(['A/a.md', 'a/b.md'])).toBe(false)
  expect(validSkillPath('../outside')).toBe(false)
})

it('preserves UTF-8 BOM and binary bytes when uploading individual files', async () => {
  const text = new TextEncoder().encode('\ufeff# Method\n{{input}}\n')
  const file = { size: text.length, name: 'method.md', arrayBuffer: async () => text.buffer } as File
  const imported = await browserSkillFile(file, 'references/method.md', packageLimits)
  expect(imported.content).toBe('\ufeff# Method\n{{input}}\n')
  expect(skillFileSize(imported)).toBe(text.length)
  const binary = new Uint8Array([0, 255, 137, 80])
  const resource = await browserSkillFile({ size: binary.length, name: 'image.bin', arrayBuffer: async () => binary.buffer } as File, 'assets/image.bin', packageLimits)
  expect(resource.encoding).toBe('base64')
  expect([...atob(resource.content)].map(char => char.charCodeAt(0))).toEqual([...binary])
  expect(sameSkillFiles([resource, imported], [imported, resource])).toBe(true)
})
