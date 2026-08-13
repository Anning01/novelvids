import { describe, expect, it } from 'vitest'
import { replaceSceneAssetSelection } from './sceneAssetSelection'

describe('replaceSceneAssetSelection', () => {
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
