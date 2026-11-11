import { tr } from '@/i18n'
import type { Scene, VideoReferenceMedia } from '@/types'
import { videoReferenceMentionSyntax } from './scenePromptReferences'

export const SHEET_ID = 'novelvids:storyboard-sheet'
const marker = videoReferenceMentionSyntax({type: 'image', url: SHEET_ID})

export function sheetReference(scene: Scene): VideoReferenceMedia | undefined {
  const sheet = scene.metadata?.storyboard_sheet as {image_url?: string; previous_image_url?: string} | undefined
  const url = sheet?.image_url || sheet?.previous_image_url
  if (url) return {type: 'image', url, mention_url: SHEET_ID, name: tr('逐镜线稿故事版')}
}

export function bindSheet(prompt: string, scene: Scene, model = '') {
  const rules = scene.storyboard_binding_rules
  const rule = rules?.[model] || rules?.general
  if (!rule || !prompt.trim() || prompt.includes(marker)) return prompt
  const line = rule.line.replace('{image}', marker)
  const oldGuidance = (scene.metadata?.storyboard_sheet as {video_guidance?: string} | undefined)?.video_guidance
  const base = !model && oldGuidance && prompt.endsWith('\n\n' + oldGuidance)
    ? prompt.slice(0, -oldGuidance.length).trimEnd() : prompt
  const lines = base.split('\n')
  const header = lines.findIndex(value => rule.headings.some(heading => value.trim() === heading ||
    (heading.endsWith(':') && value.trimStart().startsWith(heading))))
  if (header < 0) return base.trimEnd() + '\n\n' + line
  lines.splice(header + 1, 0, line)
  return lines.join('\n')
}

export function unbindSheet(prompt: string, scene: Scene) {
  const bindings = Object.values(scene.storyboard_binding_rules || {}).map(rule => rule.line.replace('{image}', marker))
  return prompt.split('\n').filter(line => !bindings.includes(line)).join('\n').split(marker).join('').trimEnd()
}

export function includeSheet(media: VideoReferenceMedia[], sheet: VideoReferenceMedia) {
  const previous = media.findIndex(m => m.mention_url === SHEET_ID || m.url === sheet.url)
  if (previous < 0) return [...media, sheet]
  return media.map((m, index) => index === previous ? sheet : m).filter((m, index) => index === previous || (m.url !== sheet.url && m.mention_url !== SHEET_ID))
}
