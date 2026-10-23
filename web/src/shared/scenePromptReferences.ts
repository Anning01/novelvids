
import { tr } from '@/i18n'
import type { VideoInputImageReference, VideoReferenceMedia } from '@/types'

const BRACED_ASSET_MENTION_PATTERN = /@\{([^}]+)\}/gu

export interface VideoInputAssetImageSource {
  assetId: number
  label: string
  mentionNames: string[]
  imageUrls: string[]
}

export function videoReferenceMentionSyntax(reference: Pick<VideoReferenceMedia, 'type' | 'url' | 'mention_url'>) {
  const label = reference.type === 'image' ? '参考图片' : '参考视频'
  return `@{${label}:${encodeURIComponent(reference.mention_url || reference.url)}}`
}

export function referencedVideoMedia(prompt: string, media: VideoReferenceMedia[]) {
  const seen = new Set<string>()
  return media.filter((reference) => {
    const identity = `${reference.type}:${reference.url}`
    if (seen.has(identity) || !prompt.includes(videoReferenceMentionSyntax(reference))) return false
    seen.add(identity)
    return true
  })
}

/**
 * 按视频供应商实际 content 顺序构建参考图清单：先放 prompt 首次引用的资产图，
 * 再放 prompt 显式引用的上传图片。content[0] 是文本，因此图片序号从 1 开始。
 */
export function buildVideoInputImageReferences(
  prompt: string,
  assets: VideoInputAssetImageSource[],
  media: VideoReferenceMedia[],
): VideoInputImageReference[] {
  const sourcesByName = new Map<string, VideoInputAssetImageSource>()
  for (const source of assets) {
    for (const name of source.mentionNames) sourcesByName.set(name, source)
  }

  const orderedAssets: VideoInputAssetImageSource[] = []
  const seenAssetIds = new Set<number>()
  const bracedRanges: Array<[number, number]> = []
  const occurrences = new Map<number, { name: string; length: number }>()
  for (const match of prompt.matchAll(BRACED_ASSET_MENTION_PATTERN)) {
    const index = match.index
    bracedRanges.push([index, index + match[0].length])
    const [name] = (match[1] || '').split('#', 1)
    if (sourcesByName.has(name)) occurrences.set(index, { name, length: match[0].length })
  }
  for (const name of sourcesByName.keys()) {
    const syntax = `@${name}`
    let index = prompt.indexOf(syntax)
    while (index >= 0) {
      const insideBracedMention = bracedRanges.some(([from, to]) => index >= from && index < to)
      const existing = occurrences.get(index)
      if (!insideBracedMention && (!existing || syntax.length > existing.length)) {
        occurrences.set(index, { name, length: syntax.length })
      }
      index = prompt.indexOf(syntax, index + syntax.length)
    }
  }
  for (const [, occurrence] of [...occurrences.entries()].sort(([left], [right]) => left - right)) {
    const source = sourcesByName.get(occurrence.name)
    if (!source || seenAssetIds.has(source.assetId)) continue
    seenAssetIds.add(source.assetId)
    orderedAssets.push(source)
  }

  const references: VideoInputImageReference[] = []
  for (const source of orderedAssets) {
    const seenUrls = new Set<string>()
    source.imageUrls.forEach((url, assetImageIndex) => {
      if (!url || seenUrls.has(url)) return
      seenUrls.add(url)
      references.push({
        number: references.length + 1,
        url,
        label: source.label,
        source: 'asset',
        assetId: source.assetId,
        assetImageIndex,
      })
    })
  }

  const referencedUploads = new Set(
    referencedVideoMedia(prompt, media)
      .filter(reference => reference.type === 'image')
      .map(reference => reference.url),
  )
  media.forEach((reference, mediaIndex) => {
    if (reference.type !== 'image' || !referencedUploads.has(reference.url)) return
    references.push({
      number: references.length + 1,
      url: reference.url,
      label: reference.name || tr('参考图片 {p0}', { p0: mediaIndex + 1 }),
      source: 'upload',
      mediaIndex,
    })
  })

  return references
}

export function readVideoReferenceMedia(value: unknown): VideoReferenceMedia[] {
  if (!Array.isArray(value)) return []
  return value.flatMap(item => {
    if (!item || typeof item !== 'object') return []
    const media = item as Record<string, unknown>
    if ((media.type !== 'image' && media.type !== 'video') || typeof media.url !== 'string' || !media.url) return []
    return [{
      library_resource_id: typeof media.library_resource_id === 'number' && Number.isInteger(media.library_resource_id) && media.library_resource_id > 0 ? media.library_resource_id : undefined,
      mention_name: typeof media.mention_name === 'string' ? media.mention_name : undefined,
      type: media.type,
      url: media.url,
      mention_url: typeof media.mention_url === 'string' ? media.mention_url : undefined,
      name: typeof media.name === 'string' ? media.name : undefined,
      content_type: typeof media.content_type === 'string' ? media.content_type : undefined,
      size_bytes: typeof media.size_bytes === 'number' ? media.size_bytes : undefined,
      width: typeof media.width === 'number' ? media.width : undefined,
      height: typeof media.height === 'number' ? media.height : undefined,
      duration: typeof media.duration === 'number' ? media.duration : undefined,
      fps: typeof media.fps === 'number' ? media.fps : undefined,
      codec: typeof media.codec === 'string' ? media.codec : undefined,
    } satisfies VideoReferenceMedia]
  })
}
