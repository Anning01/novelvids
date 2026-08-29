export type FolderEntryState = 'pending' | 'uploading' | 'ready' | 'failed' | 'invalid' | 'ignored'

export interface FolderVideoEntry {
  id: string
  file: File
  relativePath: string
  episodeNumber: number | null
  state: FolderEntryState
  progress: number
  issue: string
  uploadToken?: string
  durationSeconds?: number
}

export interface FolderBatch {
  entries: FolderVideoEntry[]
  missingEpisodes: number[]
  hasBlockingIssues: boolean
}

const patterns = [
  /第\s*(\d+)\s*[集话]/gi,
  /(^|[^a-z0-9])EP\s*0*(\d+)(?!\d)/gi,
  /(^|[^a-z0-9])E\s*0*(\d+)(?!\d)/gi,
  /(^|\D)0*(\d+)\s*集(?!\d)/gi,
]

export function parseFolderEpisode(filename: string): number | null | 'ambiguous' {
  const stem = filename.replace(/\.[^.]+$/, '')
  const numbers = new Set<number>()
  patterns.forEach(pattern => {
    pattern.lastIndex = 0
    for (const match of stem.matchAll(pattern)) {
      const raw = match[2] ?? match[1]
      const number = Number(raw)
      if (Number.isInteger(number)) numbers.add(number)
    }
  })
  const valid = [...numbers].filter(number => number >= 1 && number <= 99999)
  if (numbers.size > 1 || valid.length > 1) return 'ambiguous'
  return valid[0] ?? null
}

export function prepareFolderBatch(
  files: File[],
  allowedExtensions: string[],
  maxBytes: number,
): FolderBatch {
  const seen = new Map<number, FolderVideoEntry[]>()
  const entries = files.map((file, index): FolderVideoEntry => {
    const relativePath = file.webkitRelativePath || file.name
    const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
    const entry: FolderVideoEntry = {
      id: `${relativePath}:${file.size}:${file.lastModified}:${index}`,
      file,
      relativePath,
      episodeNumber: null,
      state: 'pending',
      progress: 0,
      issue: '',
    }
    if (!allowedExtensions.includes(extension)) {
      entry.state = 'ignored'
      entry.issue = '非 MP4/MOV 文件，已忽略'
      return entry
    }
    if (file.size <= 0 || file.size > maxBytes) {
      entry.state = 'invalid'
      entry.issue = file.size <= 0 ? '视频文件为空' : '单视频不能超过 500 MB'
      return entry
    }
    const parsed = parseFolderEpisode(file.name)
    if (parsed === 'ambiguous') {
      entry.state = 'invalid'
      entry.issue = '文件名包含多个不同集数'
      return entry
    }
    if (parsed === null) {
      entry.state = 'invalid'
      entry.issue = '文件名缺少集数信息'
      return entry
    }
    entry.episodeNumber = parsed
    const sameEpisode = seen.get(parsed) ?? []
    sameEpisode.push(entry)
    seen.set(parsed, sameEpisode)
    return entry
  })

  for (const [episode, duplicates] of seen) {
    if (duplicates.length < 2) continue
    duplicates.forEach(entry => {
      entry.state = 'invalid'
      entry.issue = `第 ${episode} 集重复`
    })
  }
  entries.sort((left, right) => {
    if (left.episodeNumber !== null && right.episodeNumber !== null) return left.episodeNumber - right.episodeNumber
    if (left.episodeNumber !== null) return -1
    if (right.episodeNumber !== null) return 1
    return left.relativePath.localeCompare(right.relativePath)
  })
  const validNumbers = entries
    .filter(entry => entry.state === 'pending' && entry.episodeNumber !== null)
    .map(entry => entry.episodeNumber as number)
  const present = new Set(validNumbers)
  const missingEpisodes = validNumbers.length
    ? Array.from(
        { length: Math.max(...validNumbers) - Math.min(...validNumbers) + 1 },
        (_, index) => Math.min(...validNumbers) + index,
      ).filter(number => !present.has(number))
    : []
  return {
    entries,
    missingEpisodes,
    hasBlockingIssues: entries.some(entry => entry.state === 'invalid') || validNumbers.length === 0,
  }
}
