import { describe, expect, it } from 'vitest'
import { buildVideoInputImageReferences, referencedVideoMedia, videoReferenceMentionSyntax } from './scenePromptReferences'

describe('scenePromptReferences', () => {
  it('only returns uploaded media explicitly referenced by the prompt', () => {
    const image = { type: 'image' as const, url: '/media/video-references/look 1.png', name: '造型图' }
    const video = { type: 'video' as const, url: '/media/video-references/motion.mp4', name: '动作.mp4' }
    const prompt = `使用 ${videoReferenceMentionSyntax(video)} 的动作`

    expect(referencedVideoMedia(prompt, [image, video])).toEqual([video])
  })

  it('maps provider image numbers to asset nicknames in request order', () => {
    const upload = { type: 'image' as const, url: '/media/upload.png', name: '动作参考' }
    const ignored = { type: 'image' as const, url: '/media/ignored.png', name: '未引用图片' }
    const prompt = `@{陈经理} 与 @{岳闻}，参考 ${videoReferenceMentionSyntax(upload)}`

    expect(buildVideoInputImageReferences(prompt, [
      { assetId: 1, label: '岳闻 · 古装形象', mentionNames: ['岳闻'], imageUrls: ['/media/yue-1.png'] },
      { assetId: 2, label: '陈经理', mentionNames: ['陈经理'], imageUrls: ['/media/chen-1.png', '/media/chen-2.png'] },
    ], [ignored, upload])).toEqual([
      { number: 1, url: '/media/chen-1.png', label: '陈经理', source: 'asset', assetId: 2, assetImageIndex: 0 },
      { number: 2, url: '/media/chen-2.png', label: '陈经理', source: 'asset', assetId: 2, assetImageIndex: 1 },
      { number: 3, url: '/media/yue-1.png', label: '岳闻 · 古装形象', source: 'asset', assetId: 1, assetImageIndex: 0 },
      { number: 4, url: '/media/upload.png', label: '动作参考', source: 'upload', mediaIndex: 1 },
    ])
  })
})
