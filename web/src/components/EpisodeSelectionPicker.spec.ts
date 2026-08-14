import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import EpisodeSelectionPicker from './EpisodeSelectionPicker.vue'

const episodes = Array.from({ length: 240 }, (_, index) => index + 1)
const mountPicker = (props: { modelValue: number[]; episodeNumbers: number[]; currentEpisode?: number }) => mount(EpisodeSelectionPicker, {
  props,
  global: { stubs: { teleport: true } },
})

describe('EpisodeSelectionPicker', () => {
  it('summarizes list storage as compact ranges', () => {
    const wrapper = mountPicker({ modelValue: [1, 2, 3, 8, 9, 20], episodeNumbers: episodes })
    expect(wrapper.get('.episode-picker__trigger').text()).toContain('第 1–3 集、第 8–9 集、第 20 集')
    expect(wrapper.get('.episode-picker__trigger').text()).toContain('6 集')
  })

  it('browses hundreds of episodes in 50-episode segments', async () => {
    const wrapper = mountPicker({ modelValue: [], episodeNumbers: episodes, currentEpisode: 123 })
    await wrapper.get('.episode-picker__trigger').trigger('click')

    const pageButtons = wrapper.findAll('.episode-picker__pages button')
    expect(pageButtons).toHaveLength(5)
    expect(pageButtons.map(button => button.text())).toEqual(['1–50', '51–100', '101–150', '151–200', '201–240'])

    await pageButtons[2].trigger('click')
    expect(wrapper.findAll('.episode-picker__grid button')).toHaveLength(50)
    expect(wrapper.findAll('.episode-picker__grid button')[0]?.text()).toBe('101')
  })

  it('supports whole-segment and individual selection while emitting a normalized list', async () => {
    const wrapper = mountPicker({ modelValue: [], episodeNumbers: episodes })
    await wrapper.get('.episode-picker__trigger').trigger('click')
    await wrapper.get('.episode-picker__grid-heading button').trigger('click')

    expect(wrapper.emitted('update:modelValue')?.at(-1)?.[0]).toEqual(episodes.slice(0, 50))
  })
})
