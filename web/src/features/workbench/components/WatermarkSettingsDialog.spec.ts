import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import WatermarkSettingsDialog from './WatermarkSettingsDialog.vue'

it('matches the reference watermark controls and five preset order', async () => {
  const wrapper = mount(WatermarkSettingsDialog, {
    props: {
      open: true,
      modelValue: { resourceUrl: '', x: 0.86, y: 0.86, scale: 0.2 },
    },
    global: { stubs: { Teleport: true } },
  })

  expect(wrapper.get('[role="dialog"]').attributes('aria-label')).toBe('设置成片水印')
  expect(wrapper.get('[aria-label="组织模板"]').element).toBeInstanceOf(HTMLSelectElement)
  expect(wrapper.get('[aria-label="组织模板"]').text()).toContain('不使用模板')
  expect(wrapper.get('[aria-label="水印位置"]').findAll('option').map(option => option.text())).toEqual([
    '左上角',
    '右上角',
    '左下角',
    '右下角',
    '居中',
  ])
  expect(wrapper.findAll('input[type="range"]').map(input => ({
    label: input.attributes('aria-label'),
    min: input.attributes('min'),
    max: input.attributes('max'),
  }))).toEqual([
    { label: '横向位置', min: '0', max: '1' },
    { label: '纵向位置', min: '0', max: '1' },
    { label: '缩放', min: '0.05', max: '1' },
  ])
})

it('emits preset and slider changes immediately and keeps close separate', async () => {
  const wrapper = mount(WatermarkSettingsDialog, {
    props: {
      open: true,
      modelValue: { resourceUrl: '', x: 0.86, y: 0.86, scale: 0.2 },
    },
    global: { stubs: { Teleport: true } },
  })

  await wrapper.get('[aria-label="水印位置"]').setValue('top-left')
  expect(wrapper.emitted('change')?.at(-1)?.[0]).toMatchObject({ x: 0.14, y: 0.14, scale: 0.2 })

  await wrapper.get('[aria-label="缩放"]').setValue(0.35)
  expect(wrapper.emitted('change')?.at(-1)?.[0]).toMatchObject({ scale: 0.35 })

  await wrapper.get('[aria-label="关闭水印设置"]').trigger('click')
  expect(wrapper.emitted('close')).toHaveLength(1)
})

it('offers the exact watermark image upload types', async () => {
  const wrapper = mount(WatermarkSettingsDialog, {
    props: {
      open: true,
      modelValue: { resourceUrl: '', x: 0.86, y: 0.86, scale: 0.2 },
    },
    global: { stubs: { Teleport: true } },
  })
  const input = wrapper.get('input[type="file"]')
  expect(input.attributes()).toMatchObject({
    accept: 'image/png,image/jpeg,image/webp',
    'aria-label': '上传水印图片',
  })

  const file = new File(['logo'], 'logo.png', { type: 'image/png' })
  Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })
  await input.trigger('change')
  expect(wrapper.emitted('upload')).toEqual([[file]])
})
