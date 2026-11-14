import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const styles = readFileSync('src/pages/RemakeProgressPage.vue', 'utf8').split('<style scoped>')[1]

describe('remake progress theme', () => {
  it.each([
    ['.remake-progress-page', '--app-canvas'],
    ['.progress-header', '--app-surface-raised'],
    ['.progress-hero', '--app-surface'],
    ['.episodes-card', '--app-surface'],
    ['.episode-item.is-failed', '--creation-danger'],
    ['.progress-footer', '--app-surface-raised'],
  ])('uses the theme for the background of %s', (selector, token) => {
    expect(styles.split(selector + ' {').slice(1).some(part =>
      part.split('}')[0].match(/background:[^;]+/)?.[0].includes('var(' + token + ')')
    )).toBe(true)
  })
})
