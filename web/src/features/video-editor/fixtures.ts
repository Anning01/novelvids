import type { EditDocument, EditorMedia } from './types'
/** Small media-free fixtures shared by editor component regression tests. */
export function editorFixture() {
  const document: EditDocument = { version: 1, width: 1280, height: 720, fps: 24, clips: [1, 2, 3].map(id => ({
    id: `v${id}`, name: `分镜 ${id}`, type: 'video', start: (id - 1) * 2, duration: 2, source: { kind: 'video', id }, trim_in: 0, speed: 1, volume: 1, scale: 1, fit: 'contain',
  })) }
  const media: EditorMedia[] = [1, 2, 3].map(id => ({ key: `video:${id}`, source: { kind: 'video', id }, kind: 'video', name: `分镜 ${id}`, url: `/media/clip-${id}.mp4`, duration: 2, sequence: id, scene_id: id }))
  return { document, media, revision: 1, updated_at: '' }
}
