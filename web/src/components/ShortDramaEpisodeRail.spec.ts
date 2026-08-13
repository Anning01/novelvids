import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { Chapter } from '@/types'
import ShortDramaEpisodeRail from './ShortDramaEpisodeRail.vue'
import episodeRailSource from './ShortDramaEpisodeRail.vue?raw'

const chapters: Chapter[] = [
  { id: 11, novel_id: 1, number: 1, name: '开端', created_at: '', updated_at: '' },
  { id: 12, novel_id: 1, number: 2, name: '第2章 追踪', created_at: '', updated_at: '' },
]

describe('ShortDramaEpisodeRail', () => {
  it('renders episode numbers and emits the selected chapter', async () => {
    const wrapper = mount(ShortDramaEpisodeRail, {
      props: { chapters, activeChapterId: 12 },
    })

    expect(wrapper.text()).toContain('集数')
    const currentButton = wrapper.get('button[aria-label="第 2 集 · 追踪"]')
    const otherButton = wrapper.get('button[aria-label="第 1 集 · 开端"]')
    expect(currentButton.attributes('aria-current')).toBe('page')
    expect(currentButton.classes()).toContain('is-active')
    expect(otherButton.classes()).not.toContain('is-active')
    expect(wrapper.findAll('.episode-rail__list .is-active')).toHaveLength(1)

    await otherButton.trigger('click')
    expect(wrapper.emitted('select')?.[0]).toEqual([chapters[0]])
  })

  it('uses an animated custom tooltip without the repeated chapter ordinal', async () => {
    const wrapper = mount(ShortDramaEpisodeRail, {
      props: { chapters, activeChapterId: 12 },
    })
    const button = wrapper.get('button[aria-label="第 2 集 · 追踪"]')

    expect(button.attributes('title')).toBeUndefined()
    await button.trigger('mouseenter')

    const tooltip = wrapper.get('[role="tooltip"]')
    expect(tooltip.text()).toContain('第 2 集')
    expect(tooltip.text()).toContain('追踪')
    expect(tooltip.text()).not.toContain('第2章')
  })

  it('keeps scrolling available without showing a scrollbar', () => {
    expect(episodeRailSource).toContain('scrollbar-width: none')
    expect(episodeRailSource).toContain('.episode-rail__list::-webkit-scrollbar')
    expect(episodeRailSource).toContain('display: none')
  })

  it('keeps an outline on unselected episode buttons', () => {
    expect(episodeRailSource).toContain('box-shadow: inset 0 0 0 1px var(--app-border)')
  })
})
