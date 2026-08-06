import type { Asset, Scene } from '@/types'

export function sceneAssetIds(scene: Scene): number[] {
  if (Array.isArray(scene.asset_ids))
    return [...new Set(scene.asset_ids.filter(id => Number.isInteger(id) && id > 0))]
  return [...new Set((scene.assets || []).map(asset => asset.id).filter(id => Number.isInteger(id) && id > 0))]
}

export function sceneAssets(scene: Scene, assets: readonly Asset[]): Asset[] {
  const byId = new Map(assets.map(asset => [asset.id, asset]))
  return sceneAssetIds(scene).flatMap(id => byId.get(id) ?? [])
}
