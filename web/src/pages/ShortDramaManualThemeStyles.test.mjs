import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const appThemeSource = readFileSync('src/app-theme.css', 'utf8')

describe('manual asset card theme contrast', () => {
  it('keeps dark-mode overlay copy and action buttons legible', () => {
    expect(appThemeSource).toContain('.asset-card .asset-card-info :is(strong,p)')
    expect(appThemeSource).toMatch(/\.asset-card \.asset-card-info :is\(strong,p\)\s*\{[^}]*color: var\(--app-text\)/s)
    expect(appThemeSource).toMatch(/\.asset-card-actions \.asset-card-action\.app-button--ghost\s*\{[^}]*background: var\(--app-surface-raised\)/s)
    expect(appThemeSource).toContain('.asset-card-action.is-danger:hover:not(:disabled)')
  })
})
