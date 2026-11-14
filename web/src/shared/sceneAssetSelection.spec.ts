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
