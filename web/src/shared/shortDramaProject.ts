import type { RouteLocationRaw } from 'vue-router'
import type { Novel } from '@/types'

export type ShortDramaMode = 'agent' | 'manual'

export interface ShortDramaProjectSettings {
  mode: ShortDramaMode | null
  aspectRatio?: string
  resolution?: string
  style?: string
  sourceFile?: string
}

export function readShortDramaSettings(project: Pick<Novel, 'author' | 'description'>): ShortDramaProjectSettings {
  const description = project.description?.trim() || ''
  const parts = description.split(' · ').map(item => item.trim()).filter(Boolean)
  const mode = project.author === 'Agent 创建' || parts[0] === 'Agent 模式'
    ? 'agent'
    : project.author === '人工创建' || parts[0] === '人工模式'
      ? 'manual'
      : null

  return {
    mode,
    aspectRatio: parts.find(item => ['16:9', '4:3', '3:4', '9:16', '21:9'].includes(item)),
    resolution: parts.find(item => ['480p', '720p', '1080p', '4K'].includes(item)),
    style: parts.find((item, index) => index > 0 && !['16:9', '4:3', '3:4', '9:16', '21:9', '480p', '720p', '1080p', '4K'].includes(item) && !item.startsWith('源剧本：')),
    sourceFile: parts.find(item => item.startsWith('源剧本：'))?.slice(4),
  }
}

export function projectEntryRoute(project: Novel): RouteLocationRaw {
  const settings = readShortDramaSettings(project)
  if (settings.mode === 'agent') return { name: 'short-drama-agent', params: { projectId: project.id } }
  if (settings.mode === 'manual') return { name: 'short-drama-manual', params: { projectId: project.id } }
  return `/novel/${project.id}`
}
