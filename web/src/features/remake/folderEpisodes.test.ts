import { describe, expect, it } from 'vitest'
import { parseFolderEpisode, prepareFolderBatch } from './folderEpisodes'

function file(name: string, size = 5): File {
  return new File([new Uint8Array(size)], name, { type: 'video/mp4' })
}

describe('folder episode parsing', () => {
  it.each([
    ['第12集.mp4', 12],
    ['第 003 话.mov', 3],
    ['Drama EP0012.mp4', 12],
    ['Drama e07.mov', 7],
    ['12集.mp4', 12],
  ])('parses %s', (name, expected) => {
    expect(parseFolderEpisode(name)).toBe(expected)
  })

  it('detects ambiguous and missing episode information', () => {
    expect(parseFolderEpisode('第1集_EP2.mp4')).toBe('ambiguous')
    expect(parseFolderEpisode('花絮.mp4')).toBeNull()
  })

  it('sorts episodes, marks duplicates and ignores non-video files', () => {
    const batch = prepareFolderBatch(
      [file('第3集.mp4'), file('第1集.mp4'), file('EP01.mov'), file('说明.txt')],
      ['mp4', 'mov'],
      500 * 1024 * 1024,
    )

    expect(batch.entries.map(entry => entry.file.name)).toEqual([
      '第1集.mp4', 'EP01.mov', '第3集.mp4', '说明.txt',
    ])
    expect(batch.entries[0].state).toBe('invalid')
    expect(batch.entries[1].issue).toContain('重复')
    expect(batch.entries[3].state).toBe('ignored')
    expect(batch.hasBlockingIssues).toBe(true)
  })

  it('reports episode gaps as a non-blocking warning', () => {
    const batch = prepareFolderBatch(
      [file('第3集.mp4'), file('第1集.mp4')],
      ['mp4', 'mov'],
      500 * 1024 * 1024,
    )
    expect(batch.missingEpisodes).toEqual([2])
    expect(batch.hasBlockingIssues).toBe(false)
  })
})
