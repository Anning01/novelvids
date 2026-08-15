import type { Component } from 'vue'
import { Box, Image as ImageIcon, Mountain, Package, Palette, ShoppingBag, UserRound } from 'lucide-vue-next'
import { AssetTypeEnum } from '@/types'

export interface AssetTypePresentationOption {
  value: string
  label: string
  icon: Component
}

export const assetTypePresentationOptions: AssetTypePresentationOption[] = [
  { value: 'image', label: '图片', icon: ImageIcon },
  { value: String(AssetTypeEnum.PERSON), label: '人物', icon: UserRound },
  { value: String(AssetTypeEnum.ITEM), label: '物品', icon: Package },
  { value: String(AssetTypeEnum.SCENE), label: '场景', icon: Mountain },
  { value: String(AssetTypeEnum.PRODUCT), label: '商品', icon: ShoppingBag },
  { value: String(AssetTypeEnum.STYLE), label: '风格', icon: Palette },
]

// PRODUCT and STYLE remain in the presentation map so legacy records keep
// their original label and icon. The current workflow only creates these
// three supported asset categories.
export const editableAssetTypeOptions = assetTypePresentationOptions.filter(option => [
  String(AssetTypeEnum.PERSON),
  String(AssetTypeEnum.ITEM),
  String(AssetTypeEnum.SCENE),
].includes(option.value))

export function assetTypeIconFor(value: string | number) {
  return assetTypePresentationOptions.find(option => option.value === String(value))?.icon ?? Box
}
