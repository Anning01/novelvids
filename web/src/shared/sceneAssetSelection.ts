export type SceneVariantSelection = number | null | Array<number | null>
export type SceneVariantBindings = Record<number, SceneVariantSelection>

export function selectedVariantIds(value: SceneVariantSelection | undefined): Array<number | null> {
  return Array.isArray(value) ? value : [value ?? null]
}

export function compactVariantSelection(values: Array<number | null>): SceneVariantSelection {
  return values.length === 1 ? values[0]! : values
}

export function readSceneVariantBindings(value: unknown): SceneVariantBindings {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  const bindings: SceneVariantBindings = {}
  for (const [key, raw] of Object.entries(value)) {
    const assetId = Number(key)
    if (!Number.isInteger(assetId) || assetId < 1) continue
    const values = Array.isArray(raw) ? raw : [raw]
    if (!values.length || !values.every(id => id === null || Number.isInteger(Number(id)) && Number(id) > 0)) continue
    bindings[assetId] = compactVariantSelection([...new Set(values.map(id => id === null ? null : Number(id)))])
  }
  return bindings
}

export interface SceneAssetSelectionState {
  selectedAssetIds: number[]
  selectedVariantIds: SceneVariantBindings
}

export interface SceneAssetReplacement {
  assetId: number
  variantId: number | null
}

export function updateSceneAssetSelection(
  state: SceneAssetSelectionState,
  selection: SceneAssetReplacement & { selected: boolean },
): SceneAssetSelectionState {
  const values = state.selectedAssetIds.includes(selection.assetId) ? selectedVariantIds(state.selectedVariantIds[selection.assetId]) : []
  const next = selection.selected ? [...new Set([...values, selection.variantId])] : values.filter(id => id !== selection.variantId)
  const bindings = { ...state.selectedVariantIds }
  // Lists distinguish explicit scene choices from legacy prompt-driven bindings.
  if (next.length) bindings[selection.assetId] = next
  else delete bindings[selection.assetId]
  return {
    selectedAssetIds: next.length ? [...new Set([...state.selectedAssetIds, selection.assetId])] : state.selectedAssetIds.filter(id => id !== selection.assetId),
    selectedVariantIds: bindings,
  }
}

export function replaceSceneAssetSelection(
  state: SceneAssetSelectionState,
  replaceAssetId: number,
  replacement: SceneAssetReplacement,
  replaceVariantId?: number | null,
): SceneAssetSelectionState {
  if (replaceVariantId !== undefined) {
    return updateSceneAssetSelection(updateSceneAssetSelection(state, { assetId: replaceAssetId, variantId: replaceVariantId, selected: false }),
      { ...replacement, selected: true })
  }
  const originalIndex = state.selectedAssetIds.indexOf(replaceAssetId)
  const selectedAssetIds = state.selectedAssetIds.filter(id => id !== replaceAssetId && id !== replacement.assetId)
  selectedAssetIds.splice(originalIndex < 0 ? selectedAssetIds.length : Math.min(originalIndex, selectedAssetIds.length), 0, replacement.assetId)
  const bindings = { ...state.selectedVariantIds }
  delete bindings[replaceAssetId]
  bindings[replacement.assetId] = replacement.variantId
  return { selectedAssetIds, selectedVariantIds: bindings }
}
