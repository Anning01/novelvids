import type { RouteLocationRaw } from 'vue-router'
import type { Novel } from '@/types'

export type ShortDramaMode = 'agent' | 'manual'

export interface ShortDramaProjectSettings {
  mode: ShortDramaMode | null
  aspectRatio?: string
  resolution?: string
  style?: string
  styleKey?: string
  customStylePrompt?: string
  sourceFile?: string
}

type ProjectSettingsSource = Pick<
  Novel,
  | 'author'
  | 'description'
  | 'workflow_kind'
  | 'aspect_ratio'
  | 'resolution'
  | 'style_key'
  | 'custom_style_prompt'
>

export function readShortDramaSettings(project: ProjectSettingsSource): ShortDramaProjectSettings {
  const description = project.description?.trim() || ''
  const parts = description.split(' · ').map(item => item.trim()).filter(Boolean)
  const mode = project.workflow_kind === 'remake'
    ? 'manual'
    : project.author === 'Agent 创建' || parts[0] === 'Agent 模式'
    ? 'agent'
    : project.author === '人工创建' || parts[0] === '人工模式'
      ? 'manual'
      : null

  const legacyAspectRatio = parts.find(item => ['16:9', '4:3', '3:4', '9:16', '21:9'].includes(item))
  const legacyResolution = parts.find(item => ['480p', '720p', '1080p', '4K', '4k'].includes(item))
  const legacyStyle = parts.find((item, index) => index > 0 && !['16:9', '4:3', '3:4', '9:16', '21:9', '480p', '720p', '1080p', '4K', '4k'].includes(item) && !item.startsWith('源剧本：'))
  const customStylePrompt = project.custom_style_prompt?.trim() || undefined
  const styleKey = project.style_key || undefined

  return {
    mode,
    aspectRatio: project.aspect_ratio || legacyAspectRatio,
    resolution: project.resolution || (legacyResolution?.toLowerCase() === '4k' ? '4k' : legacyResolution),
    style: customStylePrompt || styleKey || legacyStyle,
    styleKey,
    customStylePrompt,
    sourceFile: parts.find(item => item.startsWith('源剧本：'))?.slice(4),
  }
}

export function projectEntryRoute(project: Novel): RouteLocationRaw {
  if (project.workflow_kind === 'remake') {
    return { name: 'remake-progress', params: { projectId: project.id } }
  }
  const settings = readShortDramaSettings(project)
  if (settings.mode === 'agent') return { name: 'short-drama-agent', params: { projectId: project.id } }
  if (settings.mode === 'manual') return { name: 'short-drama-manual', params: { projectId: project.id } }
  return `/novel/${project.id}`
}
