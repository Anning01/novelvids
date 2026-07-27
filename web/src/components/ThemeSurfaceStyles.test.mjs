import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const searchFilterStyles = readFileSync('src/components/SearchFilterBar.vue', 'utf8')
const selectStyles = readFileSync('src/components/AppSelect.vue', 'utf8')
const multiSelectStyles = readFileSync('src/components/AppMultiSelect.vue', 'utf8')
const iconTileStyles = readFileSync('src/components/AppIconTile.vue', 'utf8')
const assetPageStyles = readFileSync('src/pages/VideosPage.vue', 'utf8')
const configPageStyles = readFileSync('src/pages/ConfigPage.vue', 'utf8')

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
  expect(assetPageStyles).toMatch(/\.asset-scope-switch\s*\{[^}]*background:\s*var\(--app-surface\)/s)
  expect(assetPageStyles).toMatch(/\.public-character-card\s*\{[^}]*background:\s*var\(--app-surface\)/s)
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
