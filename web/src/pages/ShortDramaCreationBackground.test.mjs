import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

it('shares the subtle CSS dot pattern between both creation entry points', () => {
  const shell = readFileSync('src/components/CreationEntryShell.vue', 'utf8')
  expect(shell).toContain('background-image: radial-gradient(circle,')
  expect(shell).toContain('var(--app-text-muted) 20%, transparent')
  expect(shell).toContain('background-size: 22px 22px')
  expect(shell).not.toContain('CreationThreadsBackground')
  expect(shell).not.toContain('<canvas')
  for (const name of ['ShortDramaPage', 'RemakeWorkshopPage']) {
    expect(readFileSync(`src/pages/${name}.vue`, 'utf8')).toContain('<CreationEntryShell')
  }
  expect(readFileSync('src/app-theme.css', 'utf8')).not.toContain('--creation-bg-image')
})
