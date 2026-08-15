import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const css = readFileSync('src/features/workbench/styles/workbench.css', 'utf8')

describe('material mention asset colors', () => {
  it('assigns a distinct accent to every image asset category', () => {
    const categories = ['person', 'scene', 'item', 'product', 'style']
    const colors = categories.map((category) => {
      const match = css.match(new RegExp(`\\.workbench-inline-mention\\.is-asset-${category}\\s*\\{[^}]*--workbench-mention-type-color:\\s*(#[0-9a-f]{6})`, 'i'))
      return match?.[1]
    })

    expect(colors.every(Boolean)).toBe(true)
    expect(new Set(colors).size).toBe(categories.length)
  })
})
