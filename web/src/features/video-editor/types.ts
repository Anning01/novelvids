export type ClipKind = 'video' | 'audio' | 'subtitle' | 'sticker'
export interface EditSource { kind: 'video' | 'asset' | 'library' | 'missing'; id: number }
interface ClipBase { id: string; type: ClipKind; name: string; start: number; duration: number }
export interface VideoClip extends ClipBase { type: 'video'; source: EditSource; trim_in: number; speed: number; volume: number; scale: number; fit: 'contain' | 'cover' }
export interface AudioClip extends ClipBase { type: 'audio'; source: EditSource; trim_in: number; volume: number; fade_in: number; fade_out: number; loop: boolean }
export interface SubtitleClip extends ClipBase { type: 'subtitle'; text: string; font: 'sans'; font_size: number; color: string; bottom: number }
export interface StickerClip extends ClipBase { type: 'sticker'; source: EditSource; x: number; y: number; scale: number; opacity: number }
export type EditClip = VideoClip | AudioClip | SubtitleClip | StickerClip
export interface EditDocument { version: 1; width: number; height: number; fps: 24 | 25 | 30 | 60; clips: EditClip[] }
export interface EditorMedia {
  key: string; source: EditSource; kind: 'video' | 'audio' | 'sticker'; name: string
  url?: string | null; poster?: string | null; duration?: number; width?: number; height?: number; fps?: number
  library_kind?: string; has_audio?: boolean; missing?: boolean; sequence?: number; scene_id?: number
}
export interface EditorDraft { revision: number; document: EditDocument; media: EditorMedia[]; updated_at: string | null }
export interface EditorCapabilities { formats: Record<string, string[]>; max_size_mb: number; max_duration: number; max_overlays: number; max_audio_tracks: number; fps: number[]; resolutions: number[]; fonts: Array<{ value: string; label: string }> }
export interface EditorExport { id: number; task_id: string; status: number; stage: string; progress: number; error: string | null; revision: number; url: string | null; created_at: string }
export type ClipPatch = Partial<Omit<VideoClip, 'id' | 'type'>> & Partial<Omit<AudioClip, 'id' | 'type'>> & Partial<Omit<SubtitleClip, 'id' | 'type'>> & Partial<Omit<StickerClip, 'id' | 'type'>>
