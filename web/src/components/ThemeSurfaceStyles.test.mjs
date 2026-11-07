import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const searchFilterStyles = readFileSync('src/components/SearchFilterBar.vue', 'utf8')
const selectStyles = readFileSync('src/components/AppSelect.vue', 'utf8')
const multiSelectStyles = readFileSync('src/components/AppMultiSelect.vue', 'utf8')
const iconTileStyles = readFileSync('src/components/AppIconTile.vue', 'utf8')
const tabsStyles = readFileSync('src/components/AppTabs.vue', 'utf8')
const assetPageStyles = readFileSync('src/pages/VideosPage.vue', 'utf8')
const configPageStyles = readFileSync('src/pages/ConfigPage.vue', 'utf8')
const catalogStyles = readFileSync('src/features/resource-library/catalog.css', 'utf8')

it('keeps unselected resource folders transparent and preserves the selected accent on hover', () => {
  expect(catalogStyles).toMatch(/\.catalog-folders>button\s*\{[^}]*background:\s*transparent/s)
  expect(catalogStyles).toMatch(/\.catalog-folders>button\.active\s*\{[^}]*background:\s*var\(--soft\)/s)
  expect(catalogStyles).not.toMatch(/\.catalog-folders>button:hover\s*\{/)
  expect(catalogStyles).toMatch(/\.catalog-folder:hover:not\(\.active\)\s*\{[^}]*background:\s*var\(--app-surface-hover\)/s)
})

it('uses shared theme tokens for reusable search and select surfaces', () => {
  expect(searchFilterStyles).toMatch(/\.search-filter-bar__search\s*\{[^}]*background:\s*var\(--app-surface\)/s)
  expect(searchFilterStyles).toMatch(/\.search-filter-bar__search input\s*\{[^}]*color:\s*var\(--app-text\)/s)
  expect(selectStyles).toMatch(/\.app-select__trigger\s*\{[^}]*background:\s*var\(--app-surface\)/s)
  expect(selectStyles).toMatch(/\.app-select__menu\s*\{[^}]*background:\s*var\(--app-surface\)/s)
  expect(multiSelectStyles).toMatch(/\.app-multi-select__trigger\s*\{[^}]*background:\s*var\(--app-surface-muted\)/s)
  expect(multiSelectStyles).toMatch(/\.app-multi-select__menu\s*\{[^}]*background:\s*var\(--app-surface\)/s)
})

it('keeps the asset library on shared light and dark surface tokens', () => {
  expect(assetPageStyles).toMatch(/\.assets-page\s*\{[^}]*background:\s*var\(--app-canvas\)/s)
  expect(assetPageStyles).not.toContain(`:label="tr('公共资产分类')"`)
  expect(assetPageStyles).toContain(`:label="tr('项目资产分类')"`)
  expect(assetPageStyles.match(/<AppTabs/g)).toHaveLength(1)
  expect(tabsStyles).toMatch(/\.app-tabs\s*\{[^}]*width:\s*100%/s)
  expect(tabsStyles).toMatch(/\.app-tabs\s*\{[^}]*border-bottom:\s*1px solid var\(--app-border\)/s)
  expect(tabsStyles).toMatch(/\.app-tabs__tab\s*\{[^}]*background:\s*transparent/s)
  expect(tabsStyles).toMatch(/\.app-tabs__tab\.is-active::after\s*\{[^}]*background:\s*var\(--app-accent\)/s)
  expect(assetPageStyles).toMatch(/\.project-asset-card\s*\{[^}]*background:\s*var\(--app-surface\)/s)
  expect(assetPageStyles).not.toMatch(/\.assets-page\s*\{[^}]*background:\s*#fff/s)
})

it('keeps model form inputs themed during focus and browser autofill', () => {
  expect(configPageStyles).toMatch(/\.model-form-grid input:focus\s*\{[^}]*background:\s*var\(--app-surface-hover\)/s)
  expect(configPageStyles).toMatch(/input:-webkit-autofill:focus\s*\{[^}]*var\(--app-surface-muted\)\s+inset/s)
  expect(configPageStyles).toContain('autocomplete="new-password"')
  expect(configPageStyles).not.toMatch(/\.model-form-grid input:focus\s*\{[^}]*background:\s*#fff/s)
})

it('uses shared surfaces instead of white blocks for icon tiles', () => {
  expect(iconTileStyles).toMatch(/\.app-icon-tile\s*\{[^}]*background:\s*color-mix\(in srgb,var\(--app-icon-tile-color\) 12%,var\(--app-surface\)\)/s)
  expect(iconTileStyles).toMatch(/border:\s*1px solid color-mix\(in srgb,var\(--app-icon-tile-color\) 18%,var\(--app-border\)\)/)
  expect(iconTileStyles).not.toMatch(/background:\s*#fff/)
})


it('shares a layered neutral dark palette across the shell, home and system fallback', () => {
  const theme = readFileSync('src/app-theme.css', 'utf8')
  const home = readFileSync('src/pages/HomePage.vue', 'utf8')
  const explicit = theme.slice(theme.indexOf(":root[data-app-theme='dark'],"), theme.indexOf('@media (prefers-color-scheme: dark)'))
  const fallback = theme.slice(theme.indexOf('@media (prefers-color-scheme: dark)'), theme.indexOf(":root[data-app-theme='dark'] body"))
  const tokens = [...explicit.matchAll(/(--app-(?:canvas|surface(?:-muted|-hover)?|fill-subtle|border(?:-strong)?|text(?:-secondary|-muted)?)):\s*(#[0-9a-f]{6});/g)]
  expect(tokens.length).toBeGreaterThanOrEqual(10)
  for (const [, name, hex] of tokens) {
    expect(hex.slice(1, 3)).toBe(hex.slice(3, 5))
    expect(hex.slice(3, 5)).toBe(hex.slice(5, 7))
    expect(fallback).toContain(`${name}: ${hex};`)
  }
  expect(explicit).toContain('--app-canvas: #161616;')
  const palette = new Map(tokens.map(([, name, hex]) => [name, parseInt(hex.slice(1, 3), 16)]))
  expect(palette.get('--app-surface')).toBeGreaterThan(palette.get('--app-canvas'))
  expect(palette.get('--app-surface-hover')).toBeGreaterThan(palette.get('--app-surface'))
  expect(theme).toMatch(/\.app-sidebar\s*\{[^}]*background:\s*var\(--app-canvas\)/s)
  expect(home).not.toMatch(/--app-(?:canvas|surface|text)[\w-]*:\s*#[0-9a-f]/)
  expect(home).toContain(".clip-home .home-atmosphere) { background: none; }")
})
