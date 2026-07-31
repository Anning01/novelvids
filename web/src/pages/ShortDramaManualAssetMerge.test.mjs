import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const pageSource = readFileSync('src/pages/ShortDramaManualPage.vue', 'utf8')

it('arms asset merging only after a two-second hover and merges on drop', () => {
  expect(pageSource).toContain(':draggable="!generatingAssetIds.has(asset.id) && !mergingAssetIds.has(asset.id)"')
  expect(pageSource).toContain('@dragenter.prevent="enterMergeTarget(asset)"')
  expect(pageSource).toContain('@drop="dropAsset($event, asset)"')
  expect(pageSource).toMatch(/mergeHoverTimer = setTimeout\(\(\) => \{[\s\S]*mergeArmedTargetId\.value = target\.id[\s\S]*\}, 2000\)/)
  expect(pageSource).toContain('const armed = mergeArmedTargetId.value === target.id')
  expect(pageSource).toContain('await api.mergeAssets(sourceId, target.id)')
})

it('uses shared theme tokens for every drag-and-merge surface', () => {
  expect(pageSource).toMatch(/\.asset-merge-overlay[\s\S]*var\(--app-surface-raised\)/)
  expect(pageSource).toMatch(/\.asset-merge-ready[\s\S]*var\(--app-border-strong\)/)
  expect(pageSource).toMatch(/\.asset-merge-ready[\s\S]*var\(--app-shadow\)/)
})
