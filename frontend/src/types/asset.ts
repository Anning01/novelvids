export type AssetType = 'person' | 'scene' | 'item'

export interface Asset {
  id: string
  novel_id: string
  asset_type: AssetType
  canonical_name: string
  aliases: string[]
  description: string | null
  base_traits: string | null
  main_image: string | null
  angle_image_1: string | null
  angle_image_2: string | null
  image_source: 'ai' | 'upload'
  is_global: boolean
  source_chapters: number[]
  last_updated_chapter: number
  created_at: string
  updated_at: string
}

export interface AssetCreate {
  asset_type: AssetType
  canonical_name: string
  aliases?: string[]
  description?: string
  base_traits?: string
  is_global?: boolean
  source_chapters?: number[]
}

export interface AssetUpdate {
  canonical_name?: string
  aliases?: string[]
  description?: string
  base_traits?: string
  main_image?: string
  angle_image_1?: string
  angle_image_2?: string
  image_source?: 'ai' | 'upload'
  is_global?: boolean
  source_chapters?: number[]
}

export interface ChapterAsset {
  id: string
  chapter_id: string
  asset_id: string
  state_description: string | null
  state_traits: string | null
  appearances: Array<{ line: number; context: string }>
  asset?: Asset
}
