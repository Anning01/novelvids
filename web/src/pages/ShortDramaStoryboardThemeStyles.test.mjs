import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const pageSource = readFileSync('src/pages/ShortDramaStoryboardPage.vue', 'utf8')
const themeSource = readFileSync('src/app-theme.css', 'utf8')
const referenceSource = readFileSync('src/components/SceneReferenceMediaBar.vue', 'utf8')

describe('分镜页面深色主题与图片回退', () => {
  it('keeps hovered chapter details and video placeholders on theme surfaces', () => {
    expect(pageSource).toMatch(/\.chapter-summary:hover\s*\{[^}]*var\(--app-surface\)[^}]*var\(--app-border\)/s)
    expect(themeSource).toContain('--app-fill-subtle: #252525')
    expect(referenceSource).toContain('background: var(--app-fill-subtle)')
    expect(referenceSource).not.toContain('@media (prefers-color-scheme: dark)')
  })

  it('stretches the embedded scroll area to the toolbar in tall storyboard rows', () => {
    const css = readFileSync('src/components/ScenePromptEditor.vue', 'utf8')
    const container = css.match(/\.scene-prompt-editor\.is-embedded\s*\{([^}]+)\}/)[1]
    const input = css.match(/\.scene-prompt-editor\.is-embedded \.scene-prompt-editor__input\s*\{([^}]+)\}/)[1]
    expect(container).toContain('align-self: stretch')
    expect(container).not.toContain('max-height: 600px')
    expect(input).toContain('min-height: 100%')
    expect(input).toContain('overflow-y: auto')
  })

  it('provides original asset images as fallbacks for prompt references', () => {
    expect(pageSource).toContain('fallbackUrl: selectedAssetImage(scene, asset)')
  })
})
