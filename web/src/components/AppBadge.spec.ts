import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppBadge from './AppBadge.vue'

describe('AppBadge', () => {
  it('uses the neutral medium appearance by default', () => {
    const wrapper = mount(AppBadge, { slots: { default: '状态' } })

    expect(wrapper.text()).toBe('状态')
    expect(wrapper.classes()).toContain('app-badge--neutral')
    expect(wrapper.classes()).toContain('app-badge--md')
  })

  it('applies semantic tone and size variants', () => {
    const wrapper = mount(AppBadge, {
      props: { tone: 'success', size: 'sm' },
      slots: { default: '完成' },
    })

    expect(wrapper.classes()).toContain('app-badge--success')
    expect(wrapper.classes()).toContain('app-badge--sm')
  })
})
