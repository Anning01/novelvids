import { describe, expect, it } from 'vitest'
import { replaceSceneAssetSelection, updateSceneAssetSelection } from './sceneAssetSelection'

describe('replaceSceneAssetSelection', () => {
  it('replaces one appearance while retaining both actors remaining forms', () => {
    expect(replaceSceneAssetSelection({
      selectedAssetIds: [1, 2], selectedVariantIds: { 1: [null, 11, 12], 2: null },
    }, 1, { assetId: 2, variantId: 21 }, 11)).toEqual({
      selectedAssetIds: [1, 2], selectedVariantIds: { 1: [null, 12], 2: [null, 21] },
    })
  })
  it('keeps base and multiple forms selected, and removes only the toggled form', () => {
    let state = { selectedAssetIds: [1], selectedVariantIds: { 1: null } } as import('./sceneAssetSelection').SceneAssetSelectionState
    state = updateSceneAssetSelection(state, { assetId: 1, variantId: 11, selected: true })
    state = updateSceneAssetSelection(state, { assetId: 1, variantId: 12, selected: true })
    expect(state).toEqual({ selectedAssetIds: [1], selectedVariantIds: { 1: [null, 11, 12] } })
    state = updateSceneAssetSelection(state, { assetId: 1, variantId: 11, selected: false })
    expect(state.selectedVariantIds).toEqual({ 1: [null, 12] })
    state = updateSceneAssetSelection(state, { assetId: 1, variantId: null, selected: false })
    expect(state).toEqual({ selectedAssetIds: [1], selectedVariantIds: { 1: [12] } })
    expect(updateSceneAssetSelection(state, { assetId: 1, variantId: 12, selected: false })).toEqual({ selectedAssetIds: [], selectedVariantIds: {} })
  })
  it('replaces an asset at the same position and moves its variant selection', () => {
    expect(replaceSceneAssetSelection({
      selectedAssetIds: [1, 2, 3],
      selectedVariantIds: { 1: 11, 2: null, 3: 31 },
    }, 2, { assetId: 4, variantId: 41 })).toEqual({
      selectedAssetIds: [1, 4, 3],
      selectedVariantIds: { 1: 11, 3: 31, 4: 41 },
    })
  })

  it('does not create a duplicate when replacing with an already selected asset', () => {
    expect(replaceSceneAssetSelection({
      selectedAssetIds: [1, 2, 3],
      selectedVariantIds: { 1: null, 2: null, 3: null },
    }, 1, { assetId: 2, variantId: 22 })).toEqual({
      selectedAssetIds: [2, 3],
      selectedVariantIds: { 2: 22, 3: null },
    })
  })
})

it('uses only chapter-associated assets and forms, without mutating historical records', async () => {
  const { chapterAssetCandidates } = await import('./sceneAssetSelection')
  const asset = {
    id: 1, novel_id: 1, asset_type: 1, canonical_name: '角色', created_at: '', updated_at: '',
    source_chapters: [1, 2], is_global: true,
    variants: [
      { id: 11, asset_id: 1, name: '第一章', chapter_numbers: [1], images: [], created_at: '', updated_at: '' },
      { id: 12, asset_id: 1, name: '第二章', chapter_numbers: [2], images: [], created_at: '', updated_at: '' },
      { id: 13, asset_id: 1, name: '未关联', chapter_numbers: [], images: [], created_at: '', updated_at: '' },
    ],
  }
  const assets = [asset, { ...asset, id: 2, source_chapters: [2] }, { ...asset, id: 3, source_chapters: [] }]
  expect(chapterAssetCandidates(assets, 1).map(item => [item.id, item.variants?.map(v => v.id)]))
    .toEqual([[1, [11]]])
  expect(chapterAssetCandidates(assets, 2).map(item => [item.id, item.variants?.map(v => v.id)]))
    .toEqual([[1, [12]], [2, [12]]])
  expect(chapterAssetCandidates(assets, undefined)).toEqual([])
  expect(asset.variants).toHaveLength(3)
})
