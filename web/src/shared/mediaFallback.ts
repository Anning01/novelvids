export function fallbackImage(event: Event, fallbackUrl?: string | null): void {
  const image = event.currentTarget
  if (!(image instanceof HTMLImageElement) || !fallbackUrl) return
  if (image.dataset.fallbackApplied === 'true') return
  image.dataset.fallbackApplied = 'true'
  image.src = fallbackUrl
}
