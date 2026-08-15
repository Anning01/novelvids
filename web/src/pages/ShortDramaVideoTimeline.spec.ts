import { parse } from '@vue/compiler-sfc'
import { describe, expect, it } from 'vitest'
import videoPageSource from './ShortDramaVideoPage.vue?raw'

describe('short drama video timeline', () => {
  it('renders a scalable ruler and uses a black stage for missing clips', () => {
    expect(videoPageSource).toContain('class="video-timeline-ruler"')
    expect(videoPageSource).toContain('aria-label="时间轴刻度尺寸"')
    expect(videoPageSource).toContain('timelineScale')
    expect(videoPageSource).toContain('class="video-stage-blackout"')
    expect(videoPageSource).toContain('@ended="advanceTimeline(true)"')
  })

  it('keeps clip borders inside the horizontal scroller during hover and focus', () => {
    const styles = parse(videoPageSource).descriptor.styles.map(block => block.content).join('\n')
    const hoverRule = styles.match(/\.video-timeline-clip:hover\s*\{([^}]*)\}/)?.[1] || ''
    const activeRule = styles.match(/(\.video-timeline-clip\.is-active,[^{]+\{[^}]*\})/)?.[1] || ''

    expect(hoverRule).toContain('border-color: var(--app-border-strong)')
    expect(hoverRule).not.toContain('transform')
    expect(activeRule).toContain(':focus-visible')
    expect(activeRule).toContain('box-shadow: inset')
  })
})
