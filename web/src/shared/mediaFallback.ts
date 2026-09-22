export function fallbackImage(event: Event, fallbackUrl?: string | null): void {
  const image = event.currentTarget
  if (!(image instanceof HTMLImageElement)) return
  const fallback = fallbackUrl?.trim()
  if (!fallback || image.dataset.fallbackApplied === 'true' || image.getAttribute('src') === fallback) {
    image.dataset.fallbackExhausted = 'true'
    image.hidden = true
    return
  }
  image.dataset.fallbackApplied = 'true'
  image.src = fallback
}
