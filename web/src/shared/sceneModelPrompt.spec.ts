import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import { cachedModelPrompt, resolveModelPrompt, type OptimizationFacts } from './sceneModelPrompt'
import type { Scene, VideoGenerationModel } from '@/types'

vi.mock('@/api', () => ({ api: { optimizeScenePrompt: vi.fn() }, retryableStatusError: vi.fn() }))

beforeEach(() => vi.clearAllMocks())

it.each(['seedance_2_5', 'seedance_2_5_flash'] as const)('reuses %s synchronously only while its optimization inputs match', async modelType => {
  const scene: Scene = { id: 1, sequence: 1, created_at: '', updated_at: '' }
  const model = { config_id: 1, model_type: modelType } as VideoGenerationModel
  const facts: OptimizationFacts = { generic_prompt: '@{少年}走向门口', duration: 6,
    aspect_ratio: '16:9', generation_mode: 'reference', submitted_media: [] }
  const prompt = '镜头缓缓推进，@{少年}走向门口。'
  const versions = { [modelType]: { input: JSON.stringify(facts), prompt } }
  expect(cachedModelPrompt(scene, model, facts, versions)).toBe(prompt)
  expect(await resolveModelPrompt(scene, model, facts, versions, new AbortController().signal)).toBe(prompt)
  expect(api.optimizeScenePrompt).not.toHaveBeenCalled()
  for (const change of [{ generic_prompt: '@{少年}停在门口' }, { duration: 8 }, { aspect_ratio: '9:16' },
    { submitted_media: [{ type: 'image' as const, label: '新增参考图' }] }]) {
    expect(cachedModelPrompt(scene, model, { ...facts, ...change }, versions)).toBeUndefined()
  }
})

it('reoptimizes a cached draft that lost named bindings even when the input text is unchanged', async () => {
  const facts: OptimizationFacts = { generic_prompt: '@{苏玄#少年}看着@{墓牌}', duration: 24,
    aspect_ratio: '16:9', generation_mode: 'reference', submitted_media: [] }
  const scene: Scene = { id: 1, sequence: 1, created_at: '', updated_at: '' }
  const model = { config_id: 1, model_type: 'wan_3' } as VideoGenerationModel
  const prompt = '[核心任务] @{苏玄#少年}看着@{墓牌}'
  vi.mocked(api.optimizeScenePrompt).mockResolvedValue({code: 0, message: '', data: {
    id: 'fixed', status: 3, task_type: 8, created_at: '',
    response_data: { scene_id: 1, model_type: 'wan_3', prompt },
  }})
  const result = await resolveModelPrompt(scene, model, facts, {wan_3: {input: JSON.stringify(facts), prompt: '苏玄看着墓牌'}}, new AbortController().signal)
  expect(api.optimizeScenePrompt).toHaveBeenCalledOnce()
  expect(result).toBe(prompt)
})
