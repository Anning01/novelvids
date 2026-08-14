import type { VideoInputImageReference, VideoReferenceMedia } from '@/types'

const ASSET_MENTION_PATTERN = /@\{([^}]+)\}|@([\w\u4e00-\u9fff·]+)/gu

export interface VideoInputAssetImageSource {
  assetId: number
  label: string
  mentionNames: string[]
  imageUrls: string[]
}

export function videoReferenceMentionSyntax(reference: Pick<VideoReferenceMedia, 'type' | 'url'>) {
  const label = reference.type === 'image' ? '参考图片' : '参考视频'
  return `@{${label}:${encodeURIComponent(reference.url)}}`
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
  for (const match of prompt.matchAll(ASSET_MENTION_PATTERN)) {
    const mention = match[1] || match[2] || ''
    const [name] = mention.split('#', 1)
    const source = sourcesByName.get(name)
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
      label: reference.name || `参考图片 ${mediaIndex + 1}`,
      source: 'upload',
      mediaIndex,
    })
  })

  return references
}
