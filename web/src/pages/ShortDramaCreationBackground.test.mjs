import { existsSync, readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const themeSource = readFileSync('src/app-theme.css', 'utf8')
const pageSource = readFileSync('src/pages/ShortDramaPage.vue', 'utf8')

describe('短剧创作页主题背景', () => {
  it('为浅色和深色主题使用对应背景资源', () => {
    expect(themeSource).toContain("--creation-bg-image: url('/background-light.png')")
    expect(themeSource).toContain("--creation-bg-image: url('/background-dark.png')")
    expect(existsSync('public/background-light.png')).toBe(true)
    expect(existsSync('public/background-dark.png')).toBe(true)
  })

  it('直接展示设计背景且不覆盖高透明度纯色遮罩', () => {
    expect(pageSource).toContain('background-image: var(--creation-bg-image, none)')
    expect(pageSource).toContain('background-size: cover')
    expect(themeSource).not.toContain('--creation-bg-tint')
    expect(pageSource).not.toContain('linear-gradient(var(--creation-bg-tint')
  })
})
