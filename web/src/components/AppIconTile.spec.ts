import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppIconTile from './AppIconTile.vue'

describe('AppIconTile', () => {
  it('renders the requested tone and size with decorative semantics', () => {
    const wrapper = mount(AppIconTile, {
      props: { tone: 'video', size: 'xl' },
      slots: { default: '<svg data-test="icon" />' },
    })

    expect(wrapper.classes()).toContain('app-icon-tile--video')
    expect(wrapper.classes()).toContain('app-icon-tile--xl')
    expect(wrapper.attributes('aria-hidden')).toBe('true')
    expect(wrapper.find('[data-test="icon"]').exists()).toBe(true)
  })
})
