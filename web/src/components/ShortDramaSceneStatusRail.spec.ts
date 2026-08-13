import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ShortDramaSceneStatusRail from './ShortDramaSceneStatusRail.vue'

describe('ShortDramaSceneStatusRail', () => {
  const items = [
    { sceneId: 11, sequence: 1, state: 'completed' as const },
    { sceneId: 12, sequence: 2, state: 'error' as const },
    { sceneId: 13, sequence: 3, state: 'pending' as const },
  ]

  it('renders completed, error and pending scenes with the active pointer', () => {
    const wrapper = mount(ShortDramaSceneStatusRail, { props: { items, activeSceneId: 12 } })

    expect(wrapper.get('[aria-label="分镜 1，已完成"]').classes()).toContain('is-completed')
    expect(wrapper.get('[aria-label="分镜 2，生成异常"]').classes()).toEqual(expect.arrayContaining(['is-error', 'is-active']))
    expect(wrapper.get('[aria-label="分镜 3，待生成"]').classes()).toContain('is-pending')
  })

  it('emits the selected scene id', async () => {
    const wrapper = mount(ShortDramaSceneStatusRail, { props: { items, activeSceneId: 11 } })
    await wrapper.get('[aria-label="分镜 3，待生成"]').trigger('click')
    expect(wrapper.emitted('select')).toEqual([[13]])
  })
})
