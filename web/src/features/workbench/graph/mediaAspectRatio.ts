const RATIO_PATTERN = /^(\d+(?:\.\d+)?)\s*[:/x×]\s*(\d+(?:\.\d+)?)$/i

function positiveNumber(value: unknown) {
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(number) && number > 0 ? number : 0
}

export function parseMediaAspectRatio(value: unknown): [number, number] | null {
  const match = typeof value === 'string' ? value.trim().match(RATIO_PATTERN) : null
  if (!match) return null
  const width = positiveNumber(match[1])
  const height = positiveNumber(match[2])
  return width > 0 && height > 0 ? [width, height] : null
}

export function mediaAspectRatioValue(value: unknown) {
  const ratio = parseMediaAspectRatio(value)
  return ratio ? ratio[0] / ratio[1] : 0
}

export function mediaAspectRatioCss(value: unknown, fallback = '16 / 9') {
  const ratio = parseMediaAspectRatio(value)
  return ratio ? `${ratio[0]} / ${ratio[1]}` : fallback
}

export function containedAspectRatioSize(value: unknown, containerValue: unknown) {
  const ratio = mediaAspectRatioValue(value)
  const containerRatio = mediaAspectRatioValue(containerValue)
  if (!ratio || !containerRatio) return { width: '100%', height: '100%' }
  if (ratio > containerRatio) return { width: '100%', height: `${containerRatio / ratio * 100}%` }
  return { width: `${ratio / containerRatio * 100}%`, height: '100%' }
}

export function mediaGalleryItemWidth(
  value: unknown,
  options: { preferredHeight?: number; minWidth?: number; maxWidth?: number } = {},
) {
  const preferredHeight = options.preferredHeight ?? 520
  const minWidth = options.minWidth ?? 360
  const maxWidth = options.maxWidth ?? 920
  const ratio = mediaAspectRatioValue(value) || 16 / 9
  return Math.round(Math.min(maxWidth, Math.max(minWidth, ratio * preferredHeight)))
}

/** Preserve media order while choosing row breaks that avoid overflow and orphaned cards. */
export function balanceMediaGalleryRows<T>(
  items: readonly T[],
  ratioForItem: (item: T) => unknown,
  options: { targetRowWidth?: number; gap?: number; maxItemsPerRow?: number } = {},
): T[][] {
  if (items.length === 0) return []
  const gap = options.gap ?? 10
  const maxItemsPerRow = Math.max(1, options.maxItemsPerRow ?? 4)
  const widths = items.map(item => mediaGalleryItemWidth(ratioForItem(item)))
  const requestedRowWidth = options.targetRowWidth ?? 1280
  const narrowestItem = Math.min(...widths)
  const widestItem = Math.max(...widths)
  const isHomogeneous = widestItem - narrowestItem <= widestItem * 0.08
  const targetRowWidth = isHomogeneous && items.length > 1
    ? Math.max(requestedRowWidth, widestItem * 2 + gap)
    : requestedRowWidth
  const bestScores = Array.from({ length: items.length + 1 }).fill(Number.POSITIVE_INFINITY) as number[]
  const nextBreaks = Array.from({ length: items.length }, (_, index) => index + 1)
  bestScores[items.length] = 0

  for (let start = items.length - 1; start >= 0; start -= 1) {
    let rowWidth = 0
    const maximumEnd = Math.min(items.length, start + maxItemsPerRow)
    for (let end = start + 1; end <= maximumEnd; end += 1) {
      rowWidth += widths[end - 1]! + (end - start > 1 ? gap : 0)
      const relativeDifference = Math.abs(rowWidth - targetRowWidth) / targetRowWidth
      const isLastRow = end === items.length
      const itemCount = end - start
      const widthPenalty = relativeDifference ** 2
        * (rowWidth > targetRowWidth ? 6 : isLastRow ? 0.45 : 1)
      const orphanPenalty = items.length > 1 && itemCount === 1
        ? (isLastRow ? 0.35 : 0.7)
        : 0
      const score = widthPenalty + orphanPenalty + bestScores[end]!
      if (score < bestScores[start]!) {
        bestScores[start] = score
        nextBreaks[start] = end
      }
    }
  }

  const rows: T[][] = []
  for (let start = 0; start < items.length;) {
    const end = nextBreaks[start] ?? start + 1
    rows.push(items.slice(start, end))
    start = end
  }
  return rows
}
