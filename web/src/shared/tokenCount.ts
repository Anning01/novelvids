/** Decimal units: 1K = 1,000 tokens; 1M = 1,000,000 tokens. */
export function formatTokenCount(value: number, decimals = 0): string {
  const count = Number.isFinite(value) ? Math.max(0, value) : 0
  if (count >= 1_000_000 || (count >= 1_000 && Number((count / 1_000).toFixed(decimals)) >= 1_000)) {
    return `${(count / 1_000_000).toFixed(decimals)}M`
  }
  if (count >= 1_000) return `${(count / 1_000).toFixed(decimals)}K`
  return String(Math.round(count))
}
