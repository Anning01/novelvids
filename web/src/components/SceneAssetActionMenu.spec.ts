import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SceneAssetActionMenu from './SceneAssetActionMenu.vue'

describe('SceneAssetActionMenu', () => {
  it('centers the more trigger and exposes edit and delete actions', async () => {
    const wrapper = mount(SceneAssetActionMenu, { props: { open: true, label: '岳闻' } })

    expect(wrapper.get('.scene-asset-actions__trigger').attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('[role="menu"]').text()).toContain('编辑')
    expect(wrapper.get('[role="menu"]').text()).toContain('删除')

    const actions = wrapper.findAll('[role="menuitem"]')
    await actions[0]!.trigger('click')
    await actions[1]!.trigger('click')
    expect(wrapper.emitted('edit')).toHaveLength(1)
    expect(wrapper.emitted('remove')).toHaveLength(1)
  })

  it('emits toggle from the centered ellipsis trigger', async () => {
    const wrapper = mount(SceneAssetActionMenu, { props: { open: false, label: '岳闻' } })
    await wrapper.get('.scene-asset-actions__trigger').trigger('click')
    expect(wrapper.emitted('toggle')).toHaveLength(1)
  })
})
