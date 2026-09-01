import { describe, expect, it } from 'vitest'
import { imageDerivativeUrl, videoPosterUrl } from './mediaDerivatives'
import { TaskStatusEnum, type Video } from '@/types'

describe('mediaDerivatives', () => {
  it('derives local thumbnails and never rewrites signed remote URLs', () => {
    expect(imageDerivativeUrl('/media/assets/actor.png')).toBe(
      '/media/assets/derivatives/actor-thumbnail.webp',
    )
    expect(imageDerivativeUrl('https://cdn.example.com/uploads/1/actor.png?token=signed', 'preview')).toBe(
      'https://cdn.example.com/uploads/1/actor.png?token=signed',
    )
    expect(imageDerivativeUrl('https://external.example.com/actor.png')).toBe(
      'https://external.example.com/actor.png',
    )
  })

  it('reads persisted video posters without touching the video URL', () => {
    const video = {
      id: 1,
      scene_id: 2,
      model_type: 1,
      status: TaskStatusEnum.COMPLETED,
      url: '/media/videos/1.mp4',
      metadata: {
        poster_url: '/media/videos/posters/1-preview.webp',
        poster_thumbnail_url: '/media/videos/posters/1-thumbnail.webp',
      },
      created_at: '',
      updated_at: '',
    } satisfies Video
    expect(videoPosterUrl(video)).toContain('preview.webp')
    expect(videoPosterUrl(video, 'thumbnail')).toContain('thumbnail.webp')
  })
})
