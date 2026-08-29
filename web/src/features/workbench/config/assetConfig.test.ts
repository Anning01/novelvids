import { describe, expect, it } from 'vitest'
import type { Asset } from '@/types'
import { AssetTypeEnum } from '@/types'
import {
  assetImageCandidates,
  assetSelectedImageCandidates,
  normalizeAssetConfig,
  patchAssetWorkbenchConfig,
} from './assetConfig'

function makeAsset(patch: Partial<Asset> = {}): Asset {
  return {
    id: 1,
    novel_id: 9,
    asset_type: AssetTypeEnum.PERSON,
    canonical_name: '角色',
    created_at: '2026-07-25T00:00:00.000Z',
    updated_at: '2026-07-25T00:00:00.000Z',
    ...patch,
  }
}

describe('asset workbench configuration', () => {
  it('normalizes missing settings to the reference defaults', () => {
    expect(normalizeAssetConfig(makeAsset({ metadata: undefined }))).toEqual({
      modelConfigId: null,
      generationCount: 1,
      clarity: '1K',
      resolution: '1K',
      aspectRatio: '16:9',
      size: '1424x800',
      outputFormat: 'png',
      format: 'PNG',
      digitalHumanAssetId: '',
      digitalHumanPreviewUrl: '',
    })
  })

  it('uses the project aspect ratio until the asset saves an explicit override', () => {
    expect(normalizeAssetConfig(makeAsset(), { aspectRatio: '9:16' }).aspectRatio).toBe('9:16')
    expect(normalizeAssetConfig(makeAsset({
      metadata: { workbench: { aspectRatio: '1:1' } },
    }), { aspectRatio: '9:16' }).aspectRatio).toBe('1:1')
  })

  it('accepts persisted values and rejects malformed settings', () => {
    expect(normalizeAssetConfig(makeAsset({
      metadata: {
        model_config_id: 27,
        workbench: {
          generationCount: 4,
          resolution: '2K',
          size: '1584x2816',
          format: 'PNG',
          digitalHumanAssetId: 'human-9',
          digitalHumanPreviewUrl: '/media/human-9.png',
        },
      },
    }))).toMatchObject({
      modelConfigId: 27,
      generationCount: 1,
      resolution: '2K',
      size: '1584x2816',
      digitalHumanAssetId: 'human-9',
      digitalHumanPreviewUrl: '/media/human-9.png',
    })

    expect(normalizeAssetConfig(makeAsset({
      metadata: {
        workbench: {
          generationCount: 99,
          resolution: '4K',
          size: 'broken',
          format: 'JPEG',
          digitalHumanAssetId: 9,
          digitalHumanPreviewUrl: 9,
        },
      },
    }))).toEqual({
      modelConfigId: null,
      generationCount: 1,
      clarity: '4K',
      resolution: '4K',
      aspectRatio: '16:9',
      size: '1424x800',
      outputFormat: 'jpeg',
      format: 'JPEG',
      digitalHumanAssetId: '',
      digitalHumanPreviewUrl: '',
    })
  })

  it('deduplicates the three real image fields and marks the main image', () => {
    const asset = makeAsset({
      main_image: '/a.png',
      angle_image_1: '/a.png',
      angle_image_2: '/b.png',
    })
    expect(assetImageCandidates(asset)).toEqual([
      { key: 'angle_image_1', url: '/a.png', isMain: true, displayIndex: 0, source: 'asset' },
      { key: 'angle_image_2', url: '/b.png', isMain: false, displayIndex: 1, source: 'asset' },
    ])
  })

  it('uses only the primary image by default and honors an explicit multi-image selection', () => {
    const base = makeAsset({
      main_image: '/main.png',
      angle_image_1: '/side.png',
      metadata: { image_gallery: ['/main.png', '/side.png', '/back.png'] },
    })

    expect(assetSelectedImageCandidates(base).map(item => item.url)).toEqual(['/main.png'])
    expect(assetSelectedImageCandidates({
      ...base,
      metadata: {
        ...base.metadata,
        selected_image_urls: ['/side.png', '/back.png'],
      },
    }).map(item => item.url)).toEqual(['/side.png', '/back.png'])
  })

  it('keeps candidate thumbnail order stable when another image becomes main', () => {
    const asset = makeAsset({
      main_image: '/b.png',
      angle_image_1: '/a.png',
      angle_image_2: '/b.png',
    })
    expect(assetImageCandidates(asset).map(item => ({ url: item.url, isMain: item.isMain }))).toEqual([
      { url: '/a.png', isMain: false },
      { url: '/b.png', isMain: true },
    ])
  })

  it('preserves unrelated metadata when writing workbench settings', () => {
    const metadata = patchAssetWorkbenchConfig(
      { source: 'chapter' },
      { ...normalizeAssetConfig(makeAsset()), generationCount: 2, size: '1024x1024' },
    )
    expect(metadata).toMatchObject({
      source: 'chapter',
      model_config_id: null,
      generation_count: 1,
      workbench: { generationCount: 1, resolution: '1K', size: '1024x1024' },
    })
  })

})
