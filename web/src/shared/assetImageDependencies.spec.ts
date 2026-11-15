import { expect, it } from 'vitest'
import { AssetTypeEnum, type Asset, type AssetVariant } from '@/types'
import { imageDependencyKeys, imageReferenceCount } from './assetImageDependencies'

const asset: Asset = { id: 1, novel_id: 1, asset_type: AssetTypeEnum.PERSON, canonical_name: '师父',
  main_image: '/master.png', created_at: '', updated_at: '' }
const variant: AssetVariant = { id: 2, asset_id: 1, name: '早年', images: [], created_at: '', updated_at: '' }

it('includes the automatic parent in the estimate and deduplicates an existing manual reference', () => {
  expect(imageDependencyKeys(asset, variant)).toEqual(['asset:1'])
  expect(imageReferenceCount(asset, variant, [asset])).toBe(1)
  expect(imageReferenceCount(asset, variant, [asset], ['/master.png'])).toBe(1)
  expect(imageReferenceCount({ ...asset, main_image: undefined }, variant, [asset])).toBe(1)
})

it('uses explicit variant references without inheriting the parents other identity references', () => {
  const parent = { ...asset, metadata: { generation_reference_assets: [{asset_id: 9}] } }
  expect(imageDependencyKeys(parent, variant)).toEqual(['asset:1'])
  expect(imageDependencyKeys(parent)).toEqual(['asset:9'])
  expect(imageDependencyKeys(parent, { ...variant, metadata: {generation_reference_assets: [{asset_id: 9, variant_id: 10}] } }))
    .toEqual(['asset:1', 'variant:10'])
})
