import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import AutoEnhancementPicker from './AutoEnhancementPicker.vue'
import AppButton from './AppButton.vue'
import type { EnhancementModel } from '@/features/video-export/api'
import { setLocale } from '@/i18n'

const models: EnhancementModel[] = [{ id: 8, name: 'HD service', resolutions: [{ value: '1080p', short_side: 1080 }, { value: '2k', short_side: 1440 }],
  pricing: { type: 'media_processing', currency: 'CNY', tiers: [{ short_side_max: 1080, fps_max: 30, price: 5 }, { short_side_max: 1080, fps_max: 120, price: 20 }] } }]
it('keeps automatic enhancement opt-in and includes only configured higher targets', async () => {
  setLocale('zh')
  const wrapper = mount(AutoEnhancementPicker, { props: { modelValue: null, models, sourceResolution: '720p', duration: 6 }, global: { components: { AppButton } } })
  await wrapper.get('[role="switch"]').trigger('click')
  expect(wrapper.emitted('update:modelValue')).toEqual([[{ model_config_id: 8, resolution: '1080p' }]])
  await wrapper.setProps({ modelValue: { model_config_id: 8, resolution: '1080p' } })
  expect(wrapper.text()).toContain('增强预计 ¥0.5000–¥2.00')
  await wrapper.get('[role="switch"]').trigger('click')
  expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([null])
  wrapper.unmount()
})
it('disables unavailable services without silently enabling enhancement', async () => {
  const wrapper = mount(AutoEnhancementPicker, { props: { modelValue: null, models: [], sourceResolution: '480p' } })
  expect(wrapper.get('[role="switch"]').attributes('disabled')).toBeDefined()
  expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  wrapper.unmount()
})
