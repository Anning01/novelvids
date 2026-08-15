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

it.each([
  ['workbench', workbenchStyles],
  ['shengshimedia', shengshimediaStyles],
])('prevents horizontal scrolling in the %s select menu', (_theme, styles) => {
  const contentRule = styles.match(/(?:^|\n)\.workbench-select__content\s*\{([^}]*)\}/)?.[1] ?? ''

  expect(contentRule).toMatch(/overflow-x:\s*hidden/)
  expect(contentRule).toMatch(/overflow-y:\s*auto/)
})

it('keeps the asset-type menu wide enough for icons and labels', () => {
  const menuRule = workbenchStyles.match(/\.workbench-node-frame__icon-select \.workbench-select__content\s*\{([^}]*)\}/)?.[1] ?? ''

  expect(menuRule).toMatch(/width:\s*132px/)
  expect(menuRule).toMatch(/min-width:\s*132px/)
})

it('allows the prompt input to shrink above the footer in the shengshimedia panel', () => {
  const editorRule = shengshimediaStyles.match(/\.workbench-prompt-panel \.workbench-mention-editor\s*\{([^}]*)\}/)?.[1] ?? ''
  const inputRule = shengshimediaStyles.match(/\.workbench-prompt-panel \.workbench-mention-editor__input\s*\{([^}]*)\}/)?.[1] ?? ''

  expect(editorRule).toMatch(/min-height:\s*0/)
  expect(editorRule).toMatch(/flex:\s*1 1 auto/)
  expect(inputRule).toMatch(/height:\s*100%/)
  expect(inputRule).toMatch(/min-height:\s*0/)
  expect(inputRule).toMatch(/max-height:\s*none/)
})
