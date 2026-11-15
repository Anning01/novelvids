import type { ComputedRef, InjectionKey } from 'vue'
import type { Asset, Scene } from '@/types'
import { mediaUrl } from '@/api'
import { tr } from '@/i18n'

export interface PreviewImage { src: string; alt: string; format?: string; label?: string }

export const storyboardGalleryKey: InjectionKey<ComputedRef<PreviewImage[]>> = Symbol('storyboardGallery')

export function storyboardGallery(scenes: Scene[]): PreviewImage[] {
  return [...scenes].sort((a, b) => a.sequence - b.sequence).flatMap(scene => {
    const sheet = scene.metadata?.storyboard_sheet as { image_url?: string; previous_image_url?: string } | undefined
    const src = sheet?.image_url || sheet?.previous_image_url
    return src ? [{ src: mediaUrl(src), alt: tr('分镜 {p0} · 线稿故事版', { p0: scene.sequence }), label: String(scene.sequence) }] : []
  })
}


export function assetGallery(assets: Asset[]): PreviewImage[] {
  return [...assets].sort((a, b) => a.asset_type - b.asset_type).flatMap(asset => [
    ...(asset.main_image ? [{src: mediaUrl(asset.main_image), alt: asset.canonical_name}] : []),
    ...(asset.variants || []).flatMap(variant => {
      const src = variant.images.find(image => Boolean(image))
      return src ? [{src: mediaUrl(src), alt: `${asset.canonical_name} · ${variant.name}`}] : []
    }),
  ])
}
