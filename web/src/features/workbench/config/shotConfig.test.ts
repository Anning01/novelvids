import { describe, expect, it } from 'vitest'
import type { Scene } from '@/types'
import {
  normalizeShotConfig,
  patchShotWorkbenchConfig,
  shotGenerationOptions,
} from './shotConfig'

const projectDefaults = { aspectRatio: '9:16' as const, resolution: '720p' as const }

function makeScene(patch: Partial<Scene> = {}): Scene {
  return {
    id: 10,
    chapter_id: 2162,
    sequence: 1,
    description: '镜头',
    prompt: '',
    duration: 6,
    created_at: '2026-07-25T00:00:00.000Z',
    updated_at: '2026-07-25T00:00:00.000Z',
    ...patch,
  }
}

describe('shot workbench configuration', () => {
  it('uses verified shot defaults', () => {
    expect(normalizeShotConfig(makeScene(), projectDefaults)).toEqual({
      duration: 6,
      aspectRatio: '9:16',
      resolution: '720p',
      useLastFrame: false,
      referenceMode: 'prompt',
      referenceModes: {},
      firstFrameUrl: '',
      lastFrameUrl: '',
      activeVideoId: null,
      modelType: null,
    })
  })

  it('clamps duration to one through thirty seconds', () => {
    expect(normalizeShotConfig(makeScene({ duration: 50 }), projectDefaults).duration).toBe(30)
    expect(normalizeShotConfig(makeScene({ duration: 0 }), projectDefaults).duration).toBe(1)
  })

  it('normalizes persisted ratios, resolutions, frames, model, version, and reference modes', () => {
    const scene = makeScene({
      metadata: {
        workbench: {
          aspectRatio: '16:9',
          resolution: '1080p',
          useLastFrame: true,
          referenceMode: 'image',
          referenceModes: { 33: 'image', 34: 'prompt', invalid: 'video' },
          firstFrameUrl: '/first.png',
          lastFrameUrl: '/last.png',
          activeVideoId: 91,
          modelType: 4,
        },
      },
    })
    expect(normalizeShotConfig(scene, projectDefaults)).toMatchObject({
      aspectRatio: '16:9',
      resolution: '1080p',
      useLastFrame: true,
      referenceMode: 'image',
      referenceModes: { 33: 'image', 34: 'prompt' },
      firstFrameUrl: '/first.png',
      lastFrameUrl: '/last.png',
      activeVideoId: 91,
      modelType: 4,
    })
  })

  it('preserves unrelated metadata when writing shot settings', () => {
    const config = normalizeShotConfig(makeScene(), projectDefaults)
    expect(patchShotWorkbenchConfig({ source: 'storyboard' }, config)).toMatchObject({
      source: 'storyboard',
      workbench: { aspectRatio: '9:16', resolution: '720p' },
    })
  })

  it('builds honest reference and keyframe generation options', () => {
    const config = {
      ...normalizeShotConfig(makeScene(), projectDefaults),
      firstFrameUrl: '/first.png',
      lastFrameUrl: '/last.png',
    }
    expect(shotGenerationOptions(config)).toEqual({
      generation_mode: 'reference',
      first_frame_url: '/first.png',
      last_frame_url: undefined,
    })
    expect(shotGenerationOptions({ ...config, useLastFrame: true })).toEqual({
      generation_mode: 'keyframes',
      first_frame_url: '/first.png',
      last_frame_url: '/last.png',
    })
  })
})
