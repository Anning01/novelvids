import { API_BASE, authHeaders } from '@/api'

const loaded = new Map<string, Promise<FontFace>>()

export function subtitleFontFamily(id: string): string {
  return id === 'sans' ? "'Noto Sans SC Variable', sans-serif" : `"Subtitle-${id}", 'Noto Sans SC Variable', sans-serif`
}

export function loadSubtitleFont(id: string): Promise<FontFace> {
  const existing = loaded.get(id)
  if (existing) return existing
  const loading = (async () => {
    const response = await fetch(`${API_BASE}/video-editor/subtitle-fonts/${encodeURIComponent(id)}`, { headers: authHeaders() })
    if (!response.ok || !response.headers.get('content-type')?.startsWith('font/')) throw new Error('Subtitle font unavailable')
    const face = await new FontFace(`Subtitle-${id}`, await response.arrayBuffer()).load()
    document.fonts.add(face)
    return face
  })().catch(error => { loaded.delete(id); throw error })
  loaded.set(id, loading)
  return loading
}
