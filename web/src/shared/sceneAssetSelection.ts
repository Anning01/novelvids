export interface SceneAssetSelectionState {
  selectedAssetIds: number[]
  selectedVariantIds: Record<number, number | null>
}

export interface SceneAssetReplacement {
  assetId: number
  variantId: number | null
}

export function replaceSceneAssetSelection(
  state: SceneAssetSelectionState,
  replaceAssetId: number,
  replacement: SceneAssetReplacement,
): SceneAssetSelectionState {
  const originalIndex = state.selectedAssetIds.indexOf(replaceAssetId)
  const selectedAssetIds = state.selectedAssetIds.filter(id => id !== replaceAssetId && id !== replacement.assetId)
  selectedAssetIds.splice(originalIndex < 0 ? selectedAssetIds.length : Math.min(originalIndex, selectedAssetIds.length), 0, replacement.assetId)

  const selectedVariantIds = { ...state.selectedVariantIds }
  delete selectedVariantIds[replaceAssetId]
  selectedVariantIds[replacement.assetId] = replacement.variantId
  return { selectedAssetIds, selectedVariantIds }
}
