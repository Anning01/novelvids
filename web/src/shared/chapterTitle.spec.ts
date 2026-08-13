import { describe, expect, it } from 'vitest'
import { episodeDisplayLabel, stripChapterOrdinal } from './chapterTitle'

describe('chapter title formatting', () => {
  it('removes chapter ordinals from historical stored titles', () => {
    expect(stripChapterOrdinal('第2章 凪光真人')).toBe('凪光真人')
    expect(stripChapterOrdinal('第一百二十回：旧城夜雨')).toBe('旧城夜雨')
  })

  it('formats an episode label without repeating chapter numbering', () => {
    expect(episodeDisplayLabel({ number: 2, name: '第2章 凪光真人' })).toBe('第 2 集 · 凪光真人')
    expect(episodeDisplayLabel({ number: 3, name: '第三章' })).toBe('第 3 集')
  })
})
