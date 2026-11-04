import type { CSSProperties } from 'vue'
import type { EditDocument, SubtitleClip, SubtitlePreset } from './types'
import { subtitleLines } from './model'

export function subtitleAppearance(clip: SubtitleClip, height: number): CSSProperties {
  const scale = height / 1080
  const width = (clip.stroke_width ?? 2) * scale
  const stroke = clip.stroke_color ?? '#000000'
  return {
    color: clip.color, fontSize: `${clip.font_size * scale}px`,
    fontWeight: clip.bold ? 700 : 400, fontStyle: clip.italic ? 'italic' : 'normal',
    textDecoration: clip.underline ? 'underline' : 'none', opacity: clip.opacity ?? 1,
    letterSpacing: `${(clip.letter_spacing ?? 0) * scale}px`,
    lineHeight: `${(clip.font_size * 1.2 + (clip.line_spacing ?? 0)) * scale}px`,
    textAlign: clip.align ?? 'center', WebkitTextStroke: `${width}px ${stroke}`, paintOrder: 'stroke fill',
    textShadow: (clip.shadow ?? 1) ? `${scale}px ${scale}px ${(clip.shadow ?? 1)*scale}px #000` : 'none',
  }
}

export function subtitleBlockWidth(clip: SubtitleClip, document: EditDocument, height: number): number {
  const size = clip.font_size * height / 1080, spacing = (clip.letter_spacing ?? 0) * height / 1080
  return Math.max(1, ...subtitleLines(clip, document).split('\n').map(line =>
    Array.from(line).reduce((sum,char)=>sum+(/[^\u0000-\u00ff]/u.test(char)?1:.55)*size,0) + Math.max(0,Array.from(line).length-1)*spacing))
}

export function presetSelected(clip: SubtitleClip, preset: SubtitlePreset) {
  return clip.color === preset.color && (clip.stroke_color ?? '#000000') === preset.stroke_color
    && (clip.stroke_width ?? 2) === preset.stroke_width && (clip.shadow ?? 1) === preset.shadow && !!clip.bold === preset.bold
}
