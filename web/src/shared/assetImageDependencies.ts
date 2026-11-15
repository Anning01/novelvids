import type { Asset, AssetVariant } from '@/types'

export function imageDependencyKeys(asset: Asset, variant?: Pick<AssetVariant, 'metadata'>): string[] {
  const keys = variant ? [`asset:${asset.id}`] : []
  const references = (variant ? variant.metadata : asset.metadata)?.generation_reference_assets
  if (Array.isArray(references)) {
    for (const item of references) {
      if (!item || typeof item !== 'object' || typeof item.asset_id !== 'number') continue
      keys.push(typeof item.variant_id === 'number' ? `variant:${item.variant_id}` : `asset:${item.asset_id}`)
    }
  }
  return [...new Set(keys)]
}

export function imageReferenceCount(asset: Asset, variant: Pick<AssetVariant, 'metadata'> | undefined, assets: Asset[], manual?: string[]): number {
  const saved = { ...asset.metadata, ...variant?.metadata }.generation_reference_images
  const sources = new Set(manual ?? (Array.isArray(saved) ? saved.filter((v): v is string => typeof v === 'string') : []))
  for (const key of imageDependencyKeys(asset, variant)) {
    const [kind, id] = key.split(':')
    const image = kind === 'asset' ? assets.find(item => item.id === Number(id))?.main_image
      : assets.flatMap(item => item.variants ?? []).find(item => item.id === Number(id))?.images[0]
    sources.add(image || key)
  }
  return sources.size
}
