import { expect, it, vi } from 'vitest'
import { api } from '@/api'
import { resolveModelPrompt, type OptimizationFacts } from './sceneModelPrompt'
import type { Scene, VideoGenerationModel } from '@/types'

vi.mock('@/api', () => ({ api: { optimizeScenePrompt: vi.fn() }, retryableStatusError: vi.fn() }))

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
