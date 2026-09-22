import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const pageSource = readFileSync('src/pages/ShortDramaStoryboardPage.vue', 'utf8')
const themeSource = readFileSync('src/app-theme.css', 'utf8')
const referenceSource = readFileSync('src/components/SceneReferenceMediaBar.vue', 'utf8')

describe('分镜页面深色主题与图片回退', () => {
  it('keeps hovered chapter details and video placeholders on theme surfaces', () => {
    expect(pageSource).toMatch(/\.chapter-summary:hover\s*\{[^}]*var\(--app-surface\)[^}]*var\(--app-border\)/s)
    expect(themeSource).toContain('--app-fill-subtle: #292521')
    expect(referenceSource).toContain('background: var(--app-fill-subtle)')
    expect(referenceSource).not.toContain('@media (prefers-color-scheme: dark)')
  })

  it('falls back from generated thumbnails to original asset images', () => {
    expect(pageSource).toContain('@error="fallbackImage($event, selectedAssetImage(scene, asset))"')
    expect(pageSource).toContain('fallbackUrl: selectedAssetImage(scene, asset)')
  })
})
