import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const source = readFileSync('src/pages/ShortDramaStoryboardPage.vue', 'utf8')

it('keeps the storyboard switch available while the workflow canvas is active', () => {
  const switchOpeningTag = source.match(/<nav[^>]*class="workspace-view-switch"[^>]*>/)?.[0] ?? ''

  expect(switchOpeningTag).not.toContain('v-if=')
  expect(source).toContain(`:active="workspaceView === 'workflow'"`)
  expect(source).toContain(`:active="workspaceView === 'storyboard'"`)
  expect(source).toContain(`@click="selectWorkspaceView('storyboard')"`)
})
