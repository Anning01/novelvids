import { describe, expect, it } from 'vitest'
import agentPageSource from '@/pages/ShortDramaAgentPage.vue?raw'
import manualPageSource from '@/pages/ShortDramaManualPage.vue?raw'
import storyboardPageSource from '@/pages/ShortDramaStoryboardPage.vue?raw'

describe('short drama workspace shell adoption', () => {
  it('keeps script, settings, and storyboard on the shared chrome', () => {
    for (const source of [agentPageSource, manualPageSource, storyboardPageSource]) {
      expect(source).toContain('<ShortDramaWorkspaceShell')
    }
    expect(agentPageSource).toContain(':show-episode-rail="false"')
    expect(manualPageSource).not.toContain('class="manual-topbar"')
    expect(storyboardPageSource).not.toContain('class="storyboard-topbar"')
  })
})
