import { mediaUrl } from '@/api'
import { tr } from '@/i18n'
import { videoReferenceMentionSyntax } from '@/shared/scenePromptReferences'
import { disambiguateMaterialMentionNames } from '@/features/workbench/components/materialMentionTypes'
import type { MaterialMention } from '@/features/workbench/components/materialMentionTypes'
import type { VideoReferenceMedia } from '@/types'

export function nameClipReference(reference: VideoReferenceMedia, existing: VideoReferenceMedia[]): VideoReferenceMedia {
  const fileName = (reference.name || '').replace(/\.[^.]+$/, '').replace(/[@{}\r\n]/g, '').trim()
  const meaningful = fileName && !/^[a-f\d_-]{20,}$/i.test(fileName)
  const prefix = reference.type === 'image' ? tr('图片') : tr('视频')
  const used = new Set(existing.map(item => item.mention_name))
  let number = 1
  while (used.has(`${prefix}${number}`)) number++
  const preferred = meaningful ? fileName.slice(0, 40) : `${prefix}${number}`
  const names = disambiguateMaterialMentionNames([...existing.map(item => ({name: item.mention_name || item.name || ''})), {name: preferred}])
  return {...reference, mention_name: names[names.length - 1]!.name}
}

export function clipReferenceMentions(references: VideoReferenceMedia[]): MaterialMention[] {
  return references.map((reference, index) => {
    const key = `${reference.type}:${reference.mention_url || reference.url}`
    const name = reference.mention_name || `${reference.type === 'image' ? tr('图片') : tr('视频')}${index + 1}`
    return {edgeKey:key,connectionKey:key,nodeKey:key,name,sourceName:name,prompt:reference.name || '',
      previewUrl:mediaUrl(reference.url),hasImage:reference.type === 'image',mediaKind:reference.type,
      mode:reference.type === 'image' ? 'reference_image' : 'reference_video'}
  })
}

export function displayClipPrompt(prompt: string, references: VideoReferenceMedia[]): string {
  const mentions = clipReferenceMentions(references)
  return references.reduce((text, reference, index) => text.split(videoReferenceMentionSyntax(reference)).join(`@{${mentions[index]!.name}}`), prompt)
}
