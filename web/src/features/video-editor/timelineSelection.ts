export interface SelectionRect { left: number; top: number; right: number; bottom: number }
export interface ClipRect extends SelectionRect { id: string }
export function clipsInRect(clips: readonly ClipRect[], box: SelectionRect): string[] {
  return clips.filter(clip => clip.left < box.right && clip.right > box.left && clip.top < box.bottom && clip.bottom > box.top).map(clip => clip.id)
}
