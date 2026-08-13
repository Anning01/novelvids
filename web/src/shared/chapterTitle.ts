import type { Chapter } from '@/types'

const CHAPTER_ORDINAL_PREFIX = /^\s*第\s*(?:\d+|[零〇一二三四五六七八九十百千万亿两]+)\s*[章回节集卷部]\s*(?:[·•:：、.．\-—_]\s*)?/u

export function stripChapterOrdinal(value: string | undefined | null): string {
  return (value || '').trim().replace(CHAPTER_ORDINAL_PREFIX, '').trim()
}

export function episodeDisplayLabel(chapter: Pick<Chapter, 'number' | 'name'>): string {
  const title = stripChapterOrdinal(chapter.name)
  return title ? `第 ${chapter.number} 集 · ${title}` : `第 ${chapter.number} 集`
}
