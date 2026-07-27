import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const workbenchStyles = readFileSync('src/features/workbench/styles/workbench.css', 'utf8')
const shengshimediaStyles = readFileSync('src/features/workbench/styles/shengshimedia-workbench.css', 'utf8')

it.each([
  ['workbench', workbenchStyles],
  ['shengshimedia', shengshimediaStyles],
])('keeps the %s select trigger background and border unchanged on hover', (_theme, styles) => {
  const hoverRule = styles.match(/\.workbench-select__trigger:hover\s*\{([^}]*)\}/)?.[1] ?? ''

  expect(hoverRule).not.toMatch(/\bbackground(?:-color)?\s*:/)
  expect(hoverRule).not.toMatch(/\bborder(?:-color)?\s*:/)
})
