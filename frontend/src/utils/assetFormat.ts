/**
 * 资产引用格式工具函数
 *
 * 前端显示格式：
 * - Vidu: @资产昵称（如 @林默）
 * - Doubao: [图N]（如 [图1]）
 *
 * 后台负责将 @昵称 转换为平台 API 所需的格式
 */

export interface AssetInfo {
  id: string
  name: string  // 资产昵称
}

/**
 * 根据平台格式化单个资产引用（用于前端显示）
 *
 * @param asset 资产信息
 * @param platform 目标平台
 * @param index 资产在列表中的索引（Doubao 用）
 */
export function formatAssetRef(
  asset: AssetInfo,
  platform: 'vidu' | 'doubao',
  index?: number
): string {
  if (platform === 'vidu') {
    // Vidu: @昵称 格式
    return `@${asset.name}`
  }
  // Doubao: [图N] 格式，index 从 1 开始
  return `[图${(index ?? 0) + 1}]`
}

/**
 * 批量格式化资产引用
 */
export function formatAssetRefs(
  assets: AssetInfo[],
  platform: 'vidu' | 'doubao'
): string[] {
  return assets.map((asset, index) => formatAssetRef(asset, platform, index))
}

/**
 * 构建资产引用映射（用于后端请求）
 *
 * @returns 昵称到 ID 的映射，后端可用于替换
 */
export function buildAssetRefMap(assets: AssetInfo[]): Record<string, string> {
  const map: Record<string, string> = {}
  for (const asset of assets) {
    map[`@${asset.name}`] = asset.id
  }
  return map
}

/**
 * 在提示词中替换资产昵称为对应的平台格式
 *
 * 输入格式: @资产昵称
 * 输出格式:
 * - Vidu: @昵称（保持不变）
 * - Doubao: [图N]（按出现顺序编号）
 */
export function formatPromptAssetRefs(
  prompt: string,
  assets: AssetInfo[],
  platform: 'vidu' | 'doubao'
): string {
  if (platform === 'vidu') {
    // Vidu 保持 @昵称 格式不变
    return prompt
  }

  // Doubao: 将 @昵称 替换为 [图N]
  let index = 0
  const assetNames = new Set(assets.map(a => a.name))

  return prompt.replace(/@([^\s@]+)/g, (match, name) => {
    if (assetNames.has(name)) {
      index++
      return `[图${index}]`
    }
    return match
  })
}
