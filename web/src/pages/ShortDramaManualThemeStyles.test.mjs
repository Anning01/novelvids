import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const appThemeSource = readFileSync('src/app-theme.css', 'utf8')

describe('manual asset card theme contrast', () => {
  it('keeps dark-mode overlay copy and action buttons legible', () => {
    expect(appThemeSource).toContain('.asset-card .asset-card-info :is(strong,p)')
    expect(appThemeSource).toContain('color: #f4f1ed')
    expect(appThemeSource).toContain('background: rgb(35 32 29 / 94%)')
    expect(appThemeSource).toContain('.asset-card-action.is-danger:hover:not(:disabled)')
  })
})
