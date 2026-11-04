import { tr } from '@/i18n'
import type { AudioClip, ClipKind, ClipPatch, EditClip, EditDocument, EditorMedia, EditSource, SubtitleClip, VideoClip } from './types'

export const sourceKey = (source: EditSource) => `${source.kind}:${source.id}`
export const cloneDocument = (value: EditDocument): EditDocument => JSON.parse(JSON.stringify(value)) as EditDocument
export const totalDuration = (value: EditDocument) => Math.max(0, ...value.clips.map(item => item.start + item.duration))
export const frameTime = (value: number, fps: number) => Math.round(Math.max(0, value) * fps) / fps
export const orderedVideos = (value: EditDocument) => value.clips.filter((clip): clip is VideoClip => clip.type === 'video').sort((a, b) => a.start - b.start)
export const activeAt = (clip: EditClip, time: number) => time >= clip.start && time < clip.start + clip.duration
export function validateDocument(document: EditDocument) {
  if (!Number.isFinite(document.width) || !Number.isFinite(document.height) || document.width < 64 || document.height < 64 || document.width * document.height > 3840 * 2160) throw new Error(tr('画布尺寸无效'))
  const ids = new Set<string>()
  for (const clip of document.clips) {
    if (ids.has(clip.id)) throw new Error(tr('片段标识不能重复'))
    ids.add(clip.id)
    if (!Number.isFinite(clip.start) || clip.start < 0 || !Number.isFinite(clip.duration) || clip.duration < 1 / document.fps - .000001) throw new Error(tr('片段时间无效'))
    if (clip.type === 'video' || clip.type === 'audio') {
      if (!Number.isFinite(clip.trim_in) || clip.trim_in < 0 || !Number.isFinite(clip.volume) || clip.volume < 0 || clip.volume > 10) throw new Error(tr('片段参数无效'))
    }
    if (clip.type === 'video' && (!Number.isFinite(clip.speed) || clip.speed < .1 || clip.speed > 20)) throw new Error(tr('片段参数无效'))
    if ('scale' in clip && (!Number.isFinite(clip.scale) || clip.scale < .1 || clip.scale > 4)) throw new Error(tr('片段参数无效'))
    if ((clip.type === 'video' || clip.type === 'sticker') && (!Number.isFinite(clip.rotation ?? 0) || Math.abs(clip.rotation ?? 0) > 180)) throw new Error(tr('片段参数无效'))
    if (clip.type === 'subtitle' && (!Number.isFinite(clip.x ?? 50) || (clip.x ?? 50) < 0 || (clip.x ?? 50) > 100)) throw new Error(tr('片段参数无效'))
    if (clip.type === 'sticker' && clip.scale_y != null && (!Number.isFinite(clip.scale_y) || clip.scale_y < .1 || clip.scale_y > 4)) throw new Error(tr('片段参数无效'))
    if (clip.type === 'sticker' && (!Number.isFinite(clip.x) || !Number.isFinite(clip.y) || clip.x < 0 || clip.x > 100 || clip.y < 0 || clip.y > 100 || clip.opacity < 0 || clip.opacity > 1)) throw new Error(tr('片段参数无效'))
    if (clip.type === 'subtitle') {
      const within = (value: number, min: number, max: number) => Number.isFinite(value) && value >= min && value <= max
      if (!within(clip.letter_spacing ?? 0, -5, 50) || !within(clip.line_spacing ?? 0, 0, 100) || !within(clip.opacity ?? 1, 0, 1)
        || !within(clip.stroke_width ?? 2, 0, 10) || !within(clip.shadow ?? 1, 0, 10)
        || !['left','center','right'].includes(clip.align ?? 'center') || !/^#[a-fA-F0-9]{6}$/.test(clip.stroke_color ?? '#000000')) throw new Error(tr('片段参数无效'))
    }
    if (clip.type === 'subtitle' && (!Number.isFinite(clip.font_size) || clip.font_size < 12 || clip.font_size > 160 || clip.bottom < 0 || clip.bottom > 100)) throw new Error(tr('片段参数无效'))
    if (clip.type === 'audio' && (clip.fade_in < 0 || clip.fade_out < 0 || Math.max(clip.fade_in, clip.fade_out) > clip.duration)) throw new Error(tr('淡入淡出时长不能超过片段时长'))
  }
  const videos = orderedVideos(document)
  if (videos.some((item, index) => index > 0 && videos[index - 1]!.start + videos[index - 1]!.duration > item.start + .001)) throw new Error(tr('视频片段不能重叠，请调整位置'))
  return document
}

export function changeClip(value: EditDocument, id: string, patch: ClipPatch, media?: EditorMedia): EditDocument {
  const next = cloneDocument(value), clip = next.clips.find(item => item.id === id)
  if (!clip) return next
  Object.assign(clip, patch)
  clip.start = frameTime(clip.start, next.fps)
  clip.duration = Math.max(1 / next.fps, frameTime(clip.duration, next.fps))
  if (clip.type === 'audio') { clip.fade_in = Math.min(clip.duration, clip.fade_in); clip.fade_out = Math.min(clip.duration, clip.fade_out) }
  if (media?.duration && (clip.type === 'video' || clip.type === 'audio') && !(clip.type === 'audio' && clip.loop)) {
    const end = clip.trim_in + clip.duration * (clip.type === 'video' ? clip.speed : 1)
    if (end > media.duration + .12 || clip.trim_in >= media.duration) throw new Error(tr('裁剪范围超过原素材'))
  }
  return validateDocument(next)
}

export function addMedia(value: EditDocument, media: EditorMedia, at: number, selectedId: string): [EditDocument, string] {
  if (media.missing || !media.url) throw new Error(tr('素材尚未就绪'))
  const next = cloneDocument(value), id = crypto.randomUUID()
  let start = frameTime(at, next.fps)
  const sourceDuration = frameTime(media.kind === 'sticker' ? 4 : media.duration || 4, next.fps)
  const remaining = Math.max(0, totalDuration(value) - start)
  const duration = media.kind !== 'video' && remaining > 0 ? Math.min(sourceDuration, remaining) : sourceDuration
  let clip: EditClip
  if (media.kind === 'video') {
    const selected = next.clips.find(item => item.id === selectedId && item.type === 'video') || orderedVideos(next).at(-1)
    start = selected ? selected.start + selected.duration : 0
    for (const other of next.clips) if (other.start >= start) other.start += duration
    clip = { id, name: media.name, type: 'video', source: media.source, start, duration, trim_in: 0, speed: 1, volume: 1, scale: 1, fit: 'contain' }
  } else if (media.kind === 'audio') clip = { id, name: media.name, type: 'audio', source: media.source, start, duration, trim_in: 0, volume: 1, fade_in: 0, fade_out: 0, loop: false }
  else clip = { id, name: media.name, type: 'sticker', source: media.source, start, duration, x: 50, y: 50, scale: 1, opacity: 1 }
  next.clips.push(clip)
  return [validateDocument(next), id]
}

export function addSubtitle(value: EditDocument, at: number, text = tr('在此输入字幕')): [EditDocument, string] {
  const next = cloneDocument(value), id = crypto.randomUUID()
  next.clips.push({ id, type: 'subtitle', name: '', start: frameTime(at, next.fps), duration: Math.min(3, Math.max(1 / next.fps, totalDuration(value) - at || 3)), text, font: 'sans', font_size: 42, color: '#ffffff', bottom: 10 })
  return [validateDocument(next), id]
}

export function splitClip(value: EditDocument, id: string, time: number): [EditDocument, string] {
  const next = cloneDocument(value), clip = next.clips.find(item => item.id === id)
  if (!clip || clip.type === 'video' && clip.source.kind === 'missing') throw new Error(tr('请选择可编辑的片段'))
  const offset = frameTime(time - clip.start, next.fps)
  if (offset < 1 / next.fps || clip.duration - offset < 1 / next.fps) throw new Error(tr('请将播放头放在片段内部'))
  const other = { ...clip, id: crypto.randomUUID(), start: clip.start + offset, duration: clip.duration - offset }
  if (other.type === 'video') other.trim_in += offset * other.speed
  if (other.type === 'audio') { other.trim_in += offset; other.fade_in = 0 }
  clip.duration = offset
  if (clip.type === 'audio') { clip.fade_out = 0; clip.fade_in = Math.min(clip.fade_in, clip.duration); if (other.type === 'audio') other.fade_out = Math.min(other.fade_out, other.duration) }
  next.clips.push(other)
  return [validateDocument(next), other.id]
}

export function duplicateClip(value: EditDocument, id: string): [EditDocument, string] {
  const original = value.clips.find(item => item.id === id)
  if (!original || original.type === 'video' && original.source.kind === 'missing') throw new Error(tr('请选择可编辑的片段'))
  return pasteClip(value, original, original.start + original.duration)
}

export function pasteClip(value: EditDocument, original: EditClip, at: number): [EditDocument, string] {
  if (original.type === 'video' && original.source.kind === 'missing') throw new Error(tr('请选择可编辑的片段'))
  const next = cloneDocument(value)
  const clip = { ...JSON.parse(JSON.stringify(original)) as EditClip, id: crypto.randomUUID(), start: Math.max(0, at) }
  if (clip.type === 'video') for (const other of next.clips) if (other.start >= clip.start) other.start += clip.duration
  next.clips.push(clip)
  return [validateDocument(next), clip.id]
}

export function resizeClip(value: EditDocument, id: string, side: 'left' | 'right', delta: number, media?: EditorMedia): EditDocument {
  const clip = value.clips.find(item => item.id === id)
  if (!clip) throw new Error(tr('请选择可编辑的片段'))
  if (side === 'right') return changeClip(value, id, { duration: frameTime(clip.duration + delta, value.fps) }, media)
  const start = frameTime(Math.max(0, clip.start + delta), value.fps), actual = start - clip.start
  const patch: ClipPatch = { start, duration: clip.duration - actual }
  if (clip.type === 'video' || clip.type === 'audio') patch.trim_in = clip.trim_in + actual * (clip.type === 'video' ? clip.speed : 1)
  return changeClip(value, id, patch, media)
}

export function trimClip(value: EditDocument, id: string, trimIn: number, trimOut: number, speed: number, media: EditorMedia): EditDocument {
  const old = value.clips.find(item => item.id === id)
  if (!old || old.type !== 'video' && old.type !== 'audio' || trimOut <= trimIn) throw new Error(tr('裁剪范围无效'))
  const next = cloneDocument(value)
  const duration = frameTime((trimOut - trimIn) / speed, value.fps)
  if (duration < 1 / value.fps) throw new Error(tr('片段至少保留一帧'))
  if (old.type === 'video') {
    const delta = duration - old.duration
    for (const other of next.clips) if (other.id !== old.id && other.start >= old.start + old.duration - .001) other.start = frameTime(other.start + delta, value.fps)
  }
  return changeClip(next, id, { trim_in: trimIn, duration, ...(old.type === 'video' ? { speed } : {}) }, media)
}

export function snapAudioStart(clip: AudioClip, start: number, clips: readonly EditClip[], tolerance: number): number {
  let snapped = start
  let nearest = tolerance
  for (const other of clips) {
    if (other.type !== 'audio' || other.id === clip.id) continue
    for (const edge of [other.start + other.duration, other.start - clip.duration]) {
      const distance = Math.abs(edge - start)
      if (edge >= 0 && distance <= nearest) {
        snapped = edge
        nearest = distance
      }
    }
  }
  return snapped
}

export function moveClip(value: EditDocument, id: string, start: number): EditDocument {
  return changeClip(value, id, { start: Math.max(0, frameTime(start, value.fps)) })
}

export function subtitleLines(clip: SubtitleClip, document: EditDocument): string {
  const size = clip.font_size * document.height / 1080
  const limit = document.width * .88
  const spacing = (clip.letter_spacing ?? 0) * document.height / 1080
  const lines: string[] = []; let line = '', used = 0
  for (const char of clip.text.replace(/\r/g, '')) {
    const weight = (/[\u3000-\u9fff\uff01-\uff60\uac00-\ud7af\p{Extended_Pictographic}]/u.test(char) ? 1 : .55) * size
    if (char === '\n' || (line && used + weight + spacing > limit)) { lines.push(line); line = ''; used = 0; if (char === '\n') continue }
    if (char.charCodeAt(0) >= 32 || char === '\t') { used += weight + (line ? spacing : 0); line += char }
  }
  lines.push(line)
  return lines.join('\n')
}

export function parseSrt(text: string, document: EditDocument): SubtitleClip[] {
  const parts = text.replace(/^\uFEFF/, '').replace(/\r/g, '').trim().split(/\n\s*\n/)
  const timestamp = (v: string) => { const [h, m, s] = v.replace(',', '.').split(':').map(Number); return h! * 3600 + m! * 60 + s! }
  const result: SubtitleClip[] = []
  for (const block of parts) {
    const lines = block.split('\n'), index = lines.findIndex(line => line.includes('-->'))
    const match = lines[index]?.match(/^(\d{2,}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2,}:\d{2}:\d{2}[,.]\d{3})\s*$/)
    if (!match || !lines.slice(index + 1).join('\n').trim()) throw new Error(tr('SRT 字幕格式无效'))
    const start = timestamp(match[1]!), end = timestamp(match[2]!)
    if (!Number.isFinite(start) || end <= start || !/^\d+:([0-5]\d):([0-5]\d)/.test(match[1]!) || !/^\d+:([0-5]\d):([0-5]\d)/.test(match[2]!)) throw new Error(tr('SRT 字幕时间无效'))
    const text = lines.slice(index + 1).join('\n')
    if (text.length > 2000) throw new Error(tr('单条字幕内容过长'))
    result.push({ id: crypto.randomUUID(), type: 'subtitle', name: '', start: frameTime(start, document.fps), duration: Math.max(1 / document.fps, frameTime(end - start, document.fps)), text, font: 'sans', font_size: 42, color: '#ffffff', bottom: 10 })
  }
  if (!result.length) throw new Error(tr('SRT 字幕格式无效'))
  return result
}

export function clipTitle(clip: EditClip): string { return clip.type === 'subtitle' ? clip.text : clip.name }
export function kindLabel(kind: ClipKind): string { return ({ video: tr('视频'), audio: 'BGM', subtitle: tr('字幕'), sticker: tr('贴纸') })[kind] }
export function audioVolume(clip: AudioClip, time: number) {
  if (!activeAt(clip, time)) return 0
  const offset = time - clip.start
  return Math.max(0, Math.min(10, clip.volume)) * (clip.fade_in ? Math.min(1, offset / clip.fade_in) : 1) * (clip.fade_out ? Math.min(1, (clip.duration - offset) / clip.fade_out) : 1)
}

export const volumeDb = (volume: number) => volume > 0 ? Math.round(20 * Math.log10(volume) * 10) / 10 : -20
export const dbVolume = (db: number) => 10 ** (db / 20)
