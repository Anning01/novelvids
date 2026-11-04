import { expect, it } from 'vitest'
import { autoEnhancementAvailable, enhancementEstimate, isVideoGenerationActive, preserveAutoEnhancement, readAutoEnhancement, resolutionShortSide } from './autoEnhancement'
import type { Video } from '@/types'

const video = (stage: string): Video => ({ id: 1, scene_id: 1, status: 3, model_type: 1, created_at: '', updated_at: '', metadata: { auto_enhancement: { stage } } })
it('validates configured higher targets and reads explicit off settings safely', () => {
  expect(readAutoEnhancement(null)).toBeNull()
  expect(readAutoEnhancement({ model_config_id: 0, resolution: '4k' })).toBeNull()
  expect(readAutoEnhancement({ model_config_id: 8, resolution: '2k' })).toEqual({ model_config_id: 8, resolution: '2k' })
  const models = [{ id: 8, name: 'HD', resolutions: [{ value: '1080p', short_side: 1080 }] }]
  expect(autoEnhancementAvailable({ model_config_id: 8, resolution: '1080p' }, models, '480p')).toBe(true)
  expect(autoEnhancementAvailable({ model_config_id: 8, resolution: '1080p' }, models, '1080p')).toBe(false)
  expect(autoEnhancementAvailable({ model_config_id: 8, resolution: '4k' }, models, '480p')).toBe(false)
  expect(resolutionShortSide('768P')).toBe(768)
  expect(resolutionShortSide('2K')).toBe(1440)
  expect(resolutionShortSide('4k')).toBe(2160)
  expect(autoEnhancementAvailable({ model_config_id: 8, resolution: '1080p' }, models, '4K')).toBe(false)
})
it('keeps polling the completed source until enhancement ends and rejects stale progress regressions', () => {
  expect(isVideoGenerationActive(video('preparing'))).toBe(true)
  expect(isVideoGenerationActive(video('enhancing'))).toBe(true)
  expect(isVideoGenerationActive(video('needs_review'))).toBe(false)
  expect(isVideoGenerationActive(video('completed'))).toBe(false)
  expect(preserveAutoEnhancement(video('completed'), video('enhancing')).metadata?.auto_enhancement).toEqual({ stage: 'completed' })
})
it('shows the configured possible cost range rather than inventing an unknown frame rate', () => {
  expect(enhancementEstimate({ type: 'media_processing', currency: 'CNY', discount: 0.5,
    tiers: [{ short_side_max: 1080, fps_max: 30, price: 5 }, { short_side_max: 1080, fps_max: 120, price: 20 }] }, 1080, 60)).toEqual({ min: 2.5, max: 10 })
  expect(enhancementEstimate(null, 1080, 8)).toBeNull()
})
