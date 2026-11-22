import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const styles = readFileSync('src/features/workbench/styles/workbench.css', 'utf8')

it('uses the current hover surface and reserves the theme accent for selected digital-human cards', () => {
  const hoverRule = styles.match(/\.media-picker-grid\s*>\s*button:hover\s*\{([^}]*)\}/)?.[1] ?? ''
  const selectedRule = styles.match(/\.media-picker-grid\s*>\s*button\.is-selected\s*\{([^}]*)\}/)?.[1] ?? ''

  expect(hoverRule).toMatch(/background:\s*var\(--app-surface-hover\)\s*!important/)
  expect(selectedRule).toMatch(/background:\s*var\(--app-accent-soft\)\s*!important/)
})
