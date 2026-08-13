import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

describe('AppSelect menu overflow', () => {
  const source = readFileSync('src/components/AppSelect.vue', 'utf8')

  it('allows vertical scrolling without displaying horizontal or visible scrollbars', () => {
    expect(source).toContain('overflow-x: hidden')
    expect(source).toContain('overflow-y: auto')
    expect(source).toContain('scrollbar-width: none')
    expect(source).toContain('.app-select__menu::-webkit-scrollbar { display: none; }')
  })
})
