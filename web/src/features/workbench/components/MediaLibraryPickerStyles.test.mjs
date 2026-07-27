import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const styles = readFileSync('src/features/workbench/styles/workbench.css', 'utf8')

it('keeps digital-human cards dark on hover and reserves purple for selection', () => {
  const hoverRule = styles.match(/\.media-picker-grid\s*>\s*button:hover\s*\{([^}]*)\}/)?.[1] ?? ''
  const selectedRule = styles.match(/\.media-picker-grid\s*>\s*button\.is-selected\s*\{([^}]*)\}/)?.[1] ?? ''

  expect(hoverRule).toMatch(/background:\s*#25221f\s*!important/)
  expect(hoverRule).not.toMatch(/#f0f0ff|#302a38/)
  expect(selectedRule).toMatch(/background:\s*#302a38\s*!important/)
})
