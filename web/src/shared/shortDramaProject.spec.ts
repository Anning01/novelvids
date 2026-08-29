import { describe, expect, it } from 'vitest'
import { projectEntryRoute, readShortDramaSettings } from './shortDramaProject'
import type { Novel } from '@/types'


describe('readShortDramaSettings', () => {
  it('prefers canonical project fields over legacy description values', () => {
    const settings = readShortDramaSettings({
      author: '人工创建',
      description: '人工模式 · 16:9 · 480p · 旧风格',
      workflow_kind: 'script',
      aspect_ratio: '9:16',
      resolution: '1080p',
      style_key: 'realistic-cinematic',
      custom_style_prompt: null,
    })

    expect(settings).toMatchObject({
      mode: 'manual',
      aspectRatio: '9:16',
      resolution: '1080p',
      styleKey: 'realistic-cinematic',
      style: 'realistic-cinematic',
    })
  })

  it('uses custom style and keeps description parsing only for legacy rows', () => {
    const custom = readShortDramaSettings({
      author: '人工创建',
      description: '人工模式 · 16:9 · 480p · 旧风格',
      workflow_kind: 'script',
      aspect_ratio: '4:3',
      resolution: '720p',
      style_key: null,
      custom_style_prompt: '  东方低饱和电影感  ',
    })
    const legacy = readShortDramaSettings({
      author: 'Agent 创建',
      description: 'Agent 模式 · 16:9 · 4K · 写实电影感 · 源剧本：demo.txt',
    })

    expect(custom.style).toBe('东方低饱和电影感')
    expect(custom.styleKey).toBeUndefined()
    expect(legacy).toMatchObject({
      mode: 'agent',
      aspectRatio: '16:9',
      resolution: '4k',
      style: '写实电影感',
      sourceFile: 'demo.txt',
    })
  })
})


it('routes remake projects through the recoverable decomposition progress page', () => {
  const project = {
    id: 88,
    name: '重制项目',
    workflow_kind: 'remake',
    created_at: '',
    updated_at: '',
  } satisfies Novel

  expect(projectEntryRoute(project)).toEqual({
    name: 'remake-progress',
    params: { projectId: 88 },
  })
})
