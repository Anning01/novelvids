import type { Asset, DigitalHuman } from '@/types'

export type ReusableAssetChoice =
  | { scope: 'public'; asset: Asset }
  | { scope: 'public'; digitalHuman: DigitalHuman }
  | { scope: 'project'; asset: Asset }
