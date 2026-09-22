import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import AgentTargetPicker from './AgentTargetPicker.vue'
import type { AgentTargetOption } from './workspace'

vi.mock('element-plus', () => ({ ElPopover: defineComponent({ props: ['visible'], emits: ['update:visible'], template: `<div><div @click="$emit('update:visible', !visible)"><slot name="reference" /></div><slot v-if="visible" /></div>` }) }))
const options: AgentTargetOption[] = [
  { target: { kind: 'asset', id: 1 }, label: '岳闻', assetType: 1 },
  { target: { kind: 'variant', id: 2 }, label: '岳闻 · 古装形象', assetType: 1 },
  { target: { kind: 'asset', id: 3 }, label: '郊区小楼', assetType: 2 },
  { target: { kind: 'asset', id: 4 }, label: '手表', assetType: 3 },
  { target: { kind: 'scene', id: 5 }, label: '分镜 1 · @{岳闻}走入小楼' },
]
const props = { open: true, modelValue: ['asset:1'], options, limit: 2, loading: false, hasMore: false, disabled: false, pending: {} }

it('filters by asset category and search, with a separate selected view', async () => {
  const wrapper = mount(AgentTargetPicker, { props })
  await wrapper.findAll('nav button').find(button => button.text() === '角色')!.trigger('click')
  expect(wrapper.findAll('input[type="checkbox"]')).toHaveLength(2)
  await wrapper.get('[aria-label="搜索修改对象"]').setValue('古装')
  expect(wrapper.findAll('input[type="checkbox"]')).toHaveLength(1)
  expect(wrapper.text()).toContain('衍生形象')
  await wrapper.get('[aria-label="搜索修改对象"]').setValue('')
  await wrapper.findAll('nav button').find(button => button.text().startsWith('已选'))!.trigger('click')
  expect(wrapper.findAll('input[type="checkbox"]')).toHaveLength(1)
  expect(wrapper.get('input[type="checkbox"]').attributes('value')).toBe('asset:1')
  expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  wrapper.unmount()
})

it('allows deselection at the limit, applies selection immediately and finishes without sending', async () => {
  const wrapper = mount(AgentTargetPicker, { props })
  await wrapper.get('input[value="scene:5"]').setValue(true)
  expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([['asset:1', 'scene:5']])
  await wrapper.setProps({ modelValue: ['asset:1', 'scene:5'] })
  expect(wrapper.get('input[value="variant:2"]').attributes('disabled')).toBeDefined()
  expect(wrapper.get('input[value="asset:1"]').attributes('disabled')).toBeUndefined()
  await wrapper.get('input[value="asset:1"]').setValue(false)
  expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([['scene:5']])
  await wrapper.findAll('button').find(button => button.text() === '完成')!.trigger('click')
  expect(wrapper.emitted('update:open')?.at(-1)).toEqual([false])
  expect(wrapper.emitted('done')).toHaveLength(1)
  wrapper.unmount()
})

it('closes only the picker on Escape and retains selection', async () => {
  const wrapper = mount(AgentTargetPicker, { props })
  await wrapper.get('[role="dialog"]').trigger('keydown', { key: 'Escape' })
  await flushPromises()
  expect(wrapper.emitted('update:open')).toEqual([[false]])
  expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  wrapper.unmount()
})
