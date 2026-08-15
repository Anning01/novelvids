import { AssetTypeEnum } from '@/types';

export type MaterialMentionMode = 'reference_image' | 'reference_video' | 'reference_audio' | 'prompt_injection';
export type MaterialMentionKind = 'image' | 'video' | 'audio' | 'text';
export type MaterialMentionAssetCategory = 'person' | 'scene' | 'item' | 'product' | 'style';

export interface MaterialMentionOption {
  nodeKey: string;
  connectionKey?: string;
  mentionKey?: string;
  name: string;
  sourceName?: string;
  prompt: string;
  previewUrl: string;
  hasImage: boolean;
  mediaKind: MaterialMentionKind;
  assetCategory?: MaterialMentionAssetCategory;
  disabledReason?: string;
}

export interface MaterialMention extends MaterialMentionOption {
  edgeKey: string;
  mode: MaterialMentionMode;
}

export function materialMentionAssetCategory(assetType?: AssetTypeEnum): MaterialMentionAssetCategory | undefined {
  return ({
    [AssetTypeEnum.PERSON]: 'person',
    [AssetTypeEnum.SCENE]: 'scene',
    [AssetTypeEnum.ITEM]: 'item',
    [AssetTypeEnum.PRODUCT]: 'product',
    [AssetTypeEnum.STYLE]: 'style',
  } as Partial<Record<AssetTypeEnum, MaterialMentionAssetCategory>>)[assetType as AssetTypeEnum];
}

export function disambiguateMaterialMentionNames<T extends { name: string }>(items: T[]): T[] {
  const usedNames = new Set<string>();
  return items.map((item) => {
    const baseName = item.name.trim();
    if (!baseName)
      return item;
    let uniqueName = baseName;
    let suffix = 2;
    while (usedNames.has(uniqueName)) {
      uniqueName = `${baseName} ${suffix}`;
      suffix += 1;
    }
    usedNames.add(uniqueName);
    return uniqueName === item.name ? item : { ...item, name: uniqueName };
  });
}
