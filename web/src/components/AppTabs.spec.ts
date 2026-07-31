import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { Bot, Settings2 } from 'lucide-vue-next'
import AppTabs from './AppTabs.vue'

const items = [
  { value: 'models', label: '模型配置', icon: Bot },
  { value: 'general', label: '通用配置', icon: Settings2 },
]

describe('AppTabs', () => {
  it('emits the selected tab and updates aria state', async () => {
    const wrapper = mount(AppTabs, {
      props: { modelValue: 'models', items, label: '设置分类' },
    })

    expect(wrapper.get('[role="tab"][aria-selected="true"]').text()).toContain('模型配置')
    await wrapper.findAll('[role="tab"]')[1].trigger('click')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['general'])
  })

  it('supports arrow-key tab switching', async () => {
    const wrapper = mount(AppTabs, {
      attachTo: document.body,
      props: { modelValue: 'models', items, label: '设置分类' },
    })

    await wrapper.findAll('[role="tab"]')[0].trigger('keydown', { key: 'ArrowRight' })
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['general'])
    wrapper.unmount()
  })
})
