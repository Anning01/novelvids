import { describe, expect, it } from 'vitest'
import type { Asset } from '@/types'
import { AssetTypeEnum } from '@/types'
import {
  ASSET_SIZE_PRESETS,
  assetImageCandidates,
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
      generationCount: 1,
      resolution: '1K',
      size: '1424x800',
      format: 'PNG',
      digitalHumanAssetId: '',
      digitalHumanPreviewUrl: '',
    })
  })

  it('accepts persisted values and rejects malformed settings', () => {
    expect(normalizeAssetConfig(makeAsset({
      metadata: {
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
      generationCount: 4,
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
      generationCount: 1,
      resolution: '1K',
      size: '1424x800',
      format: 'PNG',
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
      { key: 'angle_image_1', url: '/a.png', isMain: true },
      { key: 'angle_image_2', url: '/b.png', isMain: false },
    ])
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
      workbench: { generationCount: 2, resolution: '1K', size: '1024x1024' },
    })
  })

  it('publishes the same 1K and 2K dimension presets as the reference page', () => {
    expect(ASSET_SIZE_PRESETS.map(item => item.value)).toEqual([
      '1024x1024',
      '1152x864',
      '864x1152',
      '1424x800',
      '800x1424',
      '1248x832',
      '832x1248',
      '1568x672',
      '2048x2048',
      '2368x1776',
      '1776x2368',
      '2816x1584',
      '1584x2816',
      '2496x1664',
      '1664x2496',
      '3136x1344',
    ])
  })
})
