import { compactVideoTrack, frameTime, orderedVideos, sourceKey, validateDocument, videoSourceEnd } from './model'
import type { ClipKind, ClipPatch, EditDocument, EditorMedia } from './types'

const FIELDS: Record<ClipKind, ReadonlySet<string>> = {
  video: new Set(['volume', 'scale', 'fit', 'rotation']),
  audio: new Set(['volume', 'fade_in', 'fade_out', 'loop']),
  subtitle: new Set(['text', 'font', 'font_size', 'color', 'bottom', 'x', 'bold', 'italic', 'underline', 'letter_spacing', 'line_spacing', 'align', 'opacity', 'stroke_color', 'stroke_width', 'shadow']),
  sticker: new Set(['x', 'y', 'scale', 'scale_y', 'lock_aspect', 'rotation', 'opacity']),
}

/** One scan and one validation, with unchanged clips retaining their identities. */
export function patchClips(value: EditDocument, ids: readonly string[], patch: ClipPatch): EditDocument {
  const selected = new Set(ids), entries = Object.entries(patch)
  let changed = false
  const clips = value.clips.map(clip => {
    if (!selected.has(clip.id)) return clip
    const allowed = Object.fromEntries(entries.filter(([key, next]) => FIELDS[clip.type].has(key) && next !== undefined))
    if (!Object.keys(allowed).length) return clip
    if (clip.type === 'audio') for (const key of ['fade_in', 'fade_out']) if (key in allowed) allowed[key] = Math.min(clip.duration, Number(allowed[key]))
    if (Object.entries(allowed).every(([key, next]) => Reflect.get(clip, key) === next)) return clip
    changed = true
    return { ...clip, ...allowed }
  })
  return changed ? validateDocument({ ...value, clips }) : value
}

export function retimeClips(value: EditDocument, ids: readonly string[], speed: number, media: readonly EditorMedia[]): EditDocument {
  const selected = new Set(ids), indexed = new Map(media.map(item => [item.key, item]))
  const videos = orderedVideos(value)
  const deltas: Array<{ end: number; delta: number }> = []
  const updated = new Map(videos.filter(clip => selected.has(clip.id)).map(clip => {
    const duration = indexed.get(sourceKey(clip.source))?.duration
    const end = duration ? Math.min(duration, videoSourceEnd(clip)) : videoSourceEnd(clip)
    const nextDuration = Math.max(1 / value.fps, frameTime((end - clip.trim_in) / speed, value.fps))
    deltas.push({ end: clip.start + clip.duration, delta: nextDuration - clip.duration })
    return [clip.id, { ...clip, speed, trim_out: end, duration: nextDuration }] as const
  }))
  const clips = value.clips.map(clip => {
    if (clip.type === 'video') return updated.get(clip.id) ?? clip
    const delta = deltas.reduce((sum, change) => sum + (change.end <= clip.start + .001 ? change.delta : 0), 0)
    return delta ? { ...clip, start: frameTime(clip.start + delta, value.fps) } : clip
  })
  const next = { ...value, clips }
  return validateDocument(compactVideoTrack(next, videos.map(clip => updated.get(clip.id) ?? clip)))
}
