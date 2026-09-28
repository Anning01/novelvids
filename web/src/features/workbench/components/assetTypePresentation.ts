
import { tr } from '@/i18n'
import type { Component } from 'vue'
import { Box, Image as ImageIcon, Mountain, Package, Palette, ShoppingBag, UserRound } from 'lucide-vue-next'
import { AssetTypeEnum } from '@/types'

export interface AssetTypePresentationOption {
  value: string
  label: string
  icon: Component
}

export const assetTypePresentationOptions: AssetTypePresentationOption[] = [
  { value: 'image', get label() { return tr('图片') }, icon: ImageIcon },
  { value: String(AssetTypeEnum.PERSON), get label() { return tr('人物') }, icon: UserRound },
  { value: String(AssetTypeEnum.ITEM), get label() { return tr('物品') }, icon: Package },
  { value: String(AssetTypeEnum.SCENE), get label() { return tr('场景') }, icon: Mountain },
  { value: String(AssetTypeEnum.PRODUCT), get label() { return tr('商品') }, icon: ShoppingBag },
  { value: String(AssetTypeEnum.STYLE), get label() { return tr('风格') }, icon: Palette },
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
