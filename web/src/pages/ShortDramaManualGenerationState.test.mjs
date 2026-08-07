import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const pageSource = readFileSync('src/pages/ShortDramaManualPage.vue', 'utf8')

it('shows a dedicated animated placeholder while a reference image is generating', () => {
  expect(pageSource).toContain("'is-generating': generatingAssetIds.has(asset.id)")
  expect(pageSource).toContain('class="asset-generating-placeholder"')
  expect(pageSource).toContain('正在生成参考图')
  expect(pageSource).toMatch(/\.asset-visual\.is-generating::before[\s\S]*animation:/)
  expect(pageSource).toMatch(/\.generating-summary-dot[\s\S]*animation:/)
})

it('disables nonessential generation motion when reduced motion is requested', () => {
  expect(pageSource).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*asset-visual\.is-generating::before[\s\S]*animation: none/)
})
