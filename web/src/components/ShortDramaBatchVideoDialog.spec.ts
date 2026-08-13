import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import ShortDramaBatchVideoDialog from './ShortDramaBatchVideoDialog.vue'

const scenes = [
  { id: 11, sequence: 1, cost: 600 },
  { id: 12, sequence: 2, cost: 900, disabled: true, disabledReason: '已完成' },
  { id: 13, sequence: 3, cost: 750 },
]

afterEach(() => {
  document.body.innerHTML = ''
})

describe('ShortDramaBatchVideoDialog', () => {
  it('renders every scene while preventing unavailable scenes from being selected', () => {
    const wrapper = mount(ShortDramaBatchVideoDialog, {
      props: { open: true, scenes },
      global: { stubs: { Teleport: true } },
    })

    expect(wrapper.text()).toContain('批量生视频')
    expect(wrapper.findAll('.batch-video-scene')).toHaveLength(3)
    expect(wrapper.findAll('input[type="checkbox"]')[1]!.attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('.batch-video-scene')[1]!.attributes('title')).toBe('已完成')
  })

  it('supports selecting individual scenes and exposes a clear start action', async () => {
    const wrapper = mount(ShortDramaBatchVideoDialog, {
      props: { open: true, scenes },
      global: { stubs: { Teleport: true } },
    })

    const inputs = wrapper.findAll('input[type="checkbox"]')
    await inputs[0]!.setValue(true)
    await inputs[2]!.setValue(true)

    const submit = wrapper.find('.batch-video-dialog__submit')
    expect(submit.text()).toBe('开始')
    expect(submit.attributes('aria-label')).toContain('预计消耗 1350 点')
    await submit.trigger('click')
    expect(wrapper.emitted('generate')).toEqual([[[11, 13]]])
  })

  it('selects all eligible scenes and closes with Escape', async () => {
    const wrapper = mount(ShortDramaBatchVideoDialog, {
      props: { open: true, scenes },
      global: { stubs: { Teleport: true } },
    })

    await wrapper.find('.batch-video-dialog__select-all').trigger('click')
    expect(wrapper.find('.batch-video-dialog__submit').text()).toBe('开始')
    expect(wrapper.findAll('input[type="checkbox"]').map(input => (input.element as HTMLInputElement).checked)).toEqual([true, false, true])

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(wrapper.emitted('close')).toHaveLength(1)
  })
})
