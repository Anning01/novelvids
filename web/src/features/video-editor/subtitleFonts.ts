import { API_BASE, authHeaders } from '@/api'
import { reactive } from 'vue'

const loaded = new Map<string, Promise<FontFace>>()
const readyFonts = reactive(new Set<string>())

export function isSubtitleFontReady(id: string): boolean {
  return id === 'sans' || readyFonts.has(id)
}

export function subtitleFontFamily(id: string): string {
  const fallback = "'Noto Sans SC Variable', sans-serif"
  return id !== 'sans' && isSubtitleFontReady(id) ? `"Subtitle-${id}", ${fallback}` : fallback
}

export function loadSubtitleFont(id: string): Promise<FontFace> {
  const existing = loaded.get(id)
  if (existing) return existing
  const loading = (async () => {
    const response = await fetch(`${API_BASE}/video-editor/subtitle-fonts/${encodeURIComponent(id)}`, { headers: authHeaders() })
    if (!response.ok || !response.headers.get('content-type')?.startsWith('font/')) throw new Error('Subtitle font unavailable')
    const face = await new FontFace(`Subtitle-${id}`, await response.arrayBuffer()).load()
    document.fonts.add(face)
    readyFonts.add(id)
    return face
  })().catch(error => { loaded.delete(id); throw error })
  loaded.set(id, loading)
  return loading
}
