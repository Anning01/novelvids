import type { Scene, Video } from '@/types'
import { TaskStatusEnum } from '@/types'
import { videoDurationSeconds } from '../graph/videoMedia'
import type { WorkbenchEdge, WorkbenchNode } from '../types/workbenchTypes'

export const COMPOSER_RESOLUTIONS = ['480p', '720p', '1080p', '4k'] as const
export const COMPOSER_ASPECT_RATIOS = ['16:9', '4:3', '1:1', '3:4', '9:16', '21:9'] as const
export type ComposerResolution = typeof COMPOSER_RESOLUTIONS[number]
export type ComposerAspectRatio = typeof COMPOSER_ASPECT_RATIOS[number]
export type ComposerMoveDirection = 'up' | 'down'

export interface ComposerConfig {
  name: string
  resolution: ComposerResolution
  aspectRatio: ComposerAspectRatio
}

export interface ComposerInput {
  key: string
  title: string
  url: string
  durationSeconds: number
  orderIndex: number
  sourceKind: 'shot' | 'video_result' | 'video_media'
}

function includesValue<T extends readonly string[]>(values: T, value: unknown): value is T[number] {
  return typeof value === 'string' && values.includes(value)
}

export function normalizeComposerConfig(value: Partial<ComposerConfig> | null | undefined): ComposerConfig {
  return {
    name: typeof value?.name === 'string' && value.name.trim() ? value.name.trim() : '视频合成器',
    resolution: includesValue(COMPOSER_RESOLUTIONS, value?.resolution) ? value.resolution : '720p',
    aspectRatio: includesValue(COMPOSER_ASPECT_RATIOS, value?.aspectRatio) ? value.aspectRatio : '9:16',
  }
}

export function moveOrder(keys: string[], key: string, direction: ComposerMoveDirection) {
  const index = keys.indexOf(key)
  const nextIndex = direction === 'up' ? index - 1 : index + 1
  if (index < 0 || nextIndex < 0 || nextIndex >= keys.length) return [...keys]
  const next = [...keys]
  ;[next[index], next[nextIndex]] = [next[nextIndex]!, next[index]!]
  return next
}

function shotVideo(node: WorkbenchNode) {
  const videos = Array.isArray(node.data.videos) ? node.data.videos as Video[] : []
  const scene = node.data.scene as Scene | undefined
  const metadata = scene?.metadata && typeof scene.metadata === 'object' && !Array.isArray(scene.metadata)
    ? scene.metadata as Record<string, unknown>
    : {}
  const workbench = metadata.workbench && typeof metadata.workbench === 'object' && !Array.isArray(metadata.workbench)
    ? metadata.workbench as Record<string, unknown>
    : {}
  const activeId = Number(workbench.activeVideoId)
  return videos.find(video => video.id === activeId) || videos[0]
}

function composerInput(node: WorkbenchNode, orderIndex: number): ComposerInput | null {
  if (node.kind === 'video_media') {
    return {
      key: node.key,
      title: node.title,
      url: typeof node.data.url === 'string' ? node.data.url : '',
      durationSeconds: Number(node.data.durationSeconds) || 0,
      orderIndex,
      sourceKind: node.kind,
    }
  }
  if (node.kind === 'video_result') {
    const video = node.data.video as Video | undefined
    return {
      key: node.key,
      title: node.title,
      url: video?.url || '',
      durationSeconds: video ? videoDurationSeconds(video) : 0,
      orderIndex,
      sourceKind: node.kind,
    }
  }
  if (node.kind === 'shot') {
    const video = shotVideo(node)
    return {
      key: node.key,
      title: node.title,
      url: video?.url || '',
      durationSeconds: video ? videoDurationSeconds(video) : Number((node.data.scene as Scene | undefined)?.duration) || 0,
      orderIndex,
      sourceKind: node.kind,
    }
  }
  return null
}

export function orderedComposerInputs(nodeKey: string, nodes: WorkbenchNode[], edges: WorkbenchEdge[]): ComposerInput[] {
  const byKey = new Map(nodes.map(node => [node.key, node]))
  return edges
    .filter(edge => edge.target === nodeKey && edge.type === 'output_binding' && edge.targetHandle !== 'watermark-input')
    .sort((left, right) => left.orderIndex - right.orderIndex || left.key.localeCompare(right.key))
    .flatMap((edge) => {
      const source = byKey.get(edge.source)
      const input = source ? composerInput(source, edge.orderIndex) : null
      return input ? [input] : []
    })
}

export function chapterComposerDisabledReason(
  nodeKey: string,
  nodes: WorkbenchNode[],
  edges: WorkbenchEdge[],
) {
  const shots = nodes.filter(node => node.kind === 'shot')
  if (!shots.length) return '当前集还没有可合成的镜头'
  const connectedKeys = new Set(edges
    .filter(edge => edge.target === nodeKey && edge.type === 'output_binding' && edge.targetHandle !== 'watermark-input')
    .map(edge => edge.source))
  const hasUnsupportedInput = [...connectedKeys].some(key => nodes.find(node => node.key === key)?.kind !== 'shot')
  if (hasUnsupportedInput) return '章节成片仅支持连接当前集的生成视频镜头'
  if (shots.some(shot => !connectedKeys.has(shot.key)) || connectedKeys.size !== shots.length) {
    return `请连接当前集全部 ${shots.length} 个镜头`
  }
  const incomplete = shots.some((shot) => {
    const video = shotVideo(shot)
    return !video?.url || video.status !== TaskStatusEnum.COMPLETED
  })
  return incomplete ? '镜头视频尚未全部生成完成' : ''
}
