import type { Scene, VideoReferenceMedia } from '@/types'
import { videoReferenceMentionSyntax } from './scenePromptReferences'

export function withBlockingReference(scene: Scene, media: VideoReferenceMedia[]) {
  const map = scene.blocking_reference
  if (!map) return media
  const {type, url, name, mention_url} = map
  return [...media.filter(item => item.mention_url !== mention_url && item.url !== url), {type, url, name, mention_url}]
}

export function bindBlocking(prompt: string, scene: Scene, model = '') {
  const map = scene.blocking_reference
  if (!map || !prompt.trim()) return prompt
  const rule = map.rules[model] || map.rules.general
  const marker = videoReferenceMentionSyntax(map)
  if (!rule || prompt.includes(marker)) return prompt
  const lines = prompt.split('\n')
  const heading = lines.findIndex(line => rule.headings.some(h => line.trim().startsWith(h)))
  lines.splice(heading < 0 ? lines.length : heading + 1, 0, rule.line.replace('{image}', marker))
  return lines.join('\n')
}

export function unbindBlocking(prompt: string, scene: Scene) {
  const map = scene.blocking_reference
  if (!map) return prompt
  const marker = videoReferenceMentionSyntax(map)
  const lines = Object.values(map.rules).map(rule => rule.line.replace('{image}', marker))
  return prompt.split('\n').filter(line => !lines.includes(line)).join('\n').split(marker).join('')
}
