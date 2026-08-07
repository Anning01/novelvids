import type { Asset } from '@/types'

export interface CharacterFormMetadata {
  gender: '' | '男' | '女' | '其他（动物）'
  ageGroup: '' | '儿童' | '少年' | '青年' | '中年' | '老年'
}

function traitValue(baseTraits: string | undefined, label: string) {
  const escapedLabel = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = (baseTraits || '').match(
    new RegExp(
      `(?:^|\\n)\\s*(?:[-*]\\s*)?\\**${escapedLabel}\\**\\s*[:：]\\s*(.+?)(?=\\r?\\n|$)`,
      'i',
    ),
  )
  return match?.[1]?.trim() || ''
}

function normalizeGender(value: unknown): CharacterFormMetadata['gender'] {
  if (typeof value !== 'string') return ''
  const normalized = value.toLowerCase()
  if (/其他（动物）|动物|animal/.test(normalized)) return '其他（动物）'
  if (/女性|\bfemale\b|\bwoman\b|\bgirl\b/.test(normalized)) return '女'
  if (/男性|\bmale\b|\bman\b|\bboy\b/.test(normalized)) return '男'
  if (normalized.trim() === '女') return '女'
  if (normalized.trim() === '男') return '男'
  return ''
}

function ageGroupForNumber(age: number): CharacterFormMetadata['ageGroup'] {
  if (!Number.isFinite(age) || age < 0 || age > 150) return ''
  if (age < 12) return '儿童'
  if (age < 18) return '少年'
  if (age < 40) return '青年'
  if (age < 60) return '中年'
  return '老年'
}

function normalizeAgeGroup(value: unknown): CharacterFormMetadata['ageGroup'] {
  if (typeof value === 'number') return ageGroupForNumber(value)
  if (typeof value !== 'string') return ''
  const normalized = value.toLowerCase().trim()
  const numericAge = normalized.match(/(?<!\d)(\d{1,3})(?!\d)[-\s]*(?:岁|years?(?:[-\s]*old)?)/)
  if (numericAge?.[1]) return ageGroupForNumber(Number(numericAge[1]))
  if (/中年|middle[- ]?aged|\bmidlife\b/.test(normalized)) return '中年'
  if (
    /老年|高龄|年迈|\belderly\b|\bsenior\b|\baged\b/.test(normalized)
    || /六十|七十|八十|九十|百岁/.test(normalized)
  ) return '老年'
  if (
    /少年|青少年|\badolescent\b|\bteen(?:ager)?\b/.test(normalized)
    || /十[二三四五六七八九](?:岁|周岁)|十多岁/.test(normalized)
  ) return '少年'
  if (/儿童|幼年|孩童|\bchild(?:hood)?\b|\bkid\b/.test(normalized)) return '儿童'
  if (
    /青年|年轻成人|young[- ]?adult|\badult\b/.test(normalized)
    || /二十|三十/.test(normalized)
  ) return '青年'
  return ''
}

export function resolveCharacterFormMetadata(
  asset: Pick<Asset, 'base_traits' | 'metadata'>,
): CharacterFormMetadata {
  const metadata = asset.metadata && typeof asset.metadata === 'object'
    ? asset.metadata as Record<string, unknown>
    : {}
  return {
    gender: normalizeGender(metadata.gender || traitValue(asset.base_traits, '性别')),
    ageGroup: normalizeAgeGroup(
      metadata.age_group ?? metadata.age ?? traitValue(asset.base_traits, '年龄'),
    ),
  }
}
