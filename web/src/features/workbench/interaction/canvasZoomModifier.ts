export type CanvasZoomModifier = 'Alt' | 'Meta'

function browserPlatform() {
  if (typeof navigator === 'undefined') return ''
  const nav = navigator as Navigator & { userAgentData?: { platform?: string } }
  return nav.userAgentData?.platform || nav.platform || nav.userAgent || ''
}

export function canvasZoomModifier(platform = browserPlatform()): CanvasZoomModifier {
  return /mac|iphone|ipad|ipod/i.test(platform) ? 'Meta' : 'Alt'
}
