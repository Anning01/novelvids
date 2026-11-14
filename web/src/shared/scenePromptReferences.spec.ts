import { describe, expect, it } from 'vitest'
import type { VideoReferenceMedia } from '@/types'
import { buildVideoInputImageReferences, referencedVideoMedia, videoReferenceMentionSyntax } from './scenePromptReferences'

describe('scenePromptReferences', () => {
  it('keeps images for multiple forms of one character in mention order', () => {
    const assets = [
      { assetId: 1, variantId: null, label: '苏玄', mentionNames: ['苏玄'], imageUrls: ['/base.png'] },
      { assetId: 1, variantId: 11, label: '苏玄 · 少年', mentionNames: ['苏玄', '苏玄#少年'], imageUrls: ['/young.png'] },
      { assetId: 1, variantId: 12, label: '苏玄 · 婴儿', mentionNames: ['苏玄', '苏玄#婴儿'], imageUrls: ['/baby.png'] },
    ]
    expect(buildVideoInputImageReferences('@{苏玄#婴儿} 与 @{苏玄#少年}', assets, []).map(ref => ref.url)).toEqual(['/baby.png', '/young.png'])
    expect(buildVideoInputImageReferences('@{苏玄}', assets, []).map(ref => ref.url)).toEqual(['/base.png', '/young.png', '/baby.png'])
    expect(buildVideoInputImageReferences('@{苏玄#婴儿}', assets, [], Infinity, true).map(ref => ref.url)).toEqual(['/baby.png', '/base.png', '/young.png'])
    expect(buildVideoInputImageReferences('@{苏玄#少年}', [assets[0]!, assets[2]!], [])).toEqual([])
  })
  it('caps asset images in mention order and reserves explicit uploads', () => {
    const assets = Array.from({ length: 10 }, (_, index) => ({ assetId: index,
      label: `角色${index}`, mentionNames: [`角色${index}`], imageUrls: [`/media/${index}.png`] }))
    const upload: VideoReferenceMedia = { type: 'image', url: '/media/tail.png' }
    const prompt = assets.map(asset => `@{${asset.label}}`).join(' ') + videoReferenceMentionSyntax(upload)
    const references = buildVideoInputImageReferences(prompt, assets, [upload], 9)
    expect(references).toHaveLength(9)
    expect(references.slice(0, 8).map(reference => reference.url)).toEqual(assets.slice(0, 8).map(asset => asset.imageUrls[0]))
    expect(references[8]).toMatchObject({ number: 9, source: 'upload', url: upload.url })
    expect(buildVideoInputImageReferences(prompt, assets, [], 9)).toHaveLength(9)
  })

  it('keeps explicitly bound assets in optimized drafts alongside the indexed storyboard image', () => {
    const sheet = { type: 'image' as const, url: '/media/sheet.png', name: '故事版' }
    const assets = [
      { assetId: 8, label: '墓碑', mentionNames: ['墓碑'], imageUrls: ['/media/prop.png'] },
      { assetId: 3, label: '山坡', mentionNames: ['山坡'], imageUrls: ['/media/location.png'] },
    ]
    const general = '镜头推向墓碑。'
    const active = videoReferenceMentionSyntax(sheet)
    expect(buildVideoInputImageReferences(general, assets, [sheet], 3, true, active)
      .map(({number, label}) => [number, label])).toEqual([[1, '山坡'], [2, '墓碑'], [3, '故事版']])
    expect(buildVideoInputImageReferences(general, assets, [sheet], 3)).toEqual([])
  })

  it('numbers shared image URLs only once across assets and uploads', () => {
    const upload: VideoReferenceMedia = { type: 'image', url: '/media/shared.png' }
    expect(buildVideoInputImageReferences(`@{甲}@{乙}${videoReferenceMentionSyntax(upload)}`, [
      { assetId: 1, label: '甲', mentionNames: ['甲'], imageUrls: [upload.url] },
      { assetId: 2, label: '乙', mentionNames: ['乙'], imageUrls: [upload.url] },
    ], [upload], 9)).toHaveLength(1)
  })

  it('only returns uploaded media explicitly referenced by the prompt', () => {
    const image = { type: 'image' as const, url: '/media/video-references/look 1.png', name: '造型图' }
    const video = { type: 'video' as const, url: '/media/video-references/motion.mp4', name: '动作.mp4' }
    const prompt = `使用 ${videoReferenceMentionSyntax(video)} 的动作`

    expect(referencedVideoMedia(prompt, [image, video])).toEqual([video])
  })

  it('OSS 签名 URL 更新后仍通过稳定地址匹配 Prompt', () => {
    const image: VideoReferenceMedia = {
      type: 'image',
      url: 'https://oss.example.com/last.png?signature=renewed',
      mention_url: 'uploads/1/last.png',
    }
    const prompt = `${videoReferenceMentionSyntax(image)} 作为本镜头首帧`

    expect(prompt).toContain(encodeURIComponent('uploads/1/last.png'))
    expect(referencedVideoMedia(prompt, [image])).toEqual([image])
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

  it('recognizes legacy asset mentions even when Chinese prose follows without a separator', () => {
    expect(buildVideoInputImageReferences('@羽宁沿着步道走，@羽宁家公寓在远处。', [
      { assetId: 1, label: '羽宁', mentionNames: ['羽宁'], imageUrls: ['/media/yuning.png'] },
      { assetId: 2, label: '羽宁家公寓', mentionNames: ['羽宁家公寓'], imageUrls: ['/media/home.png'] },
    ], [])).toEqual([
      { number: 1, url: '/media/yuning.png', label: '羽宁', source: 'asset', assetId: 1, assetImageIndex: 0 },
      { number: 2, url: '/media/home.png', label: '羽宁家公寓', source: 'asset', assetId: 2, assetImageIndex: 0 },
    ])
  })
})

it('preserves library identity and stable mention address when reopening saved references', async () => {
  const { readVideoReferenceMedia } = await import('./scenePromptReferences')
  const saved = readVideoReferenceMedia([
    { type: 'video', url: 'https://cdn.invalid/motion.mp4', mention_url: 'uploads/1/motion.mp4', library_resource_id: 7, name: 'Motion', duration: 4 },
    { type: 'image', url: '/media/legacy.png' },
    { type: 'video', url: '/media/invalid.mp4', library_resource_id: -1 },
    { type: 'audio', url: '/media/a.wav' },
  ])
  expect(saved).toHaveLength(3)
  expect(saved[0]).toMatchObject({ library_resource_id: 7, mention_url: 'uploads/1/motion.mp4', duration: 4 })
  expect(saved[1]?.library_resource_id).toBeUndefined()
  expect(saved[2]?.library_resource_id).toBeUndefined()
})
