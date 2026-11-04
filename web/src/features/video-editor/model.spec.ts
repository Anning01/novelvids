import { describe, expect, it } from 'vitest'
import { addMedia, addSubtitle, audioVolume, changeClip, duplicateClip, moveClip, parseSrt, splitClip, subtitleLines, trimClip } from './model'
import type { EditDocument, EditorMedia, VideoClip, AudioClip, SubtitleClip } from './types'
const video: VideoClip = { id: 'v', type: 'video', name: 'First', start: 0, duration: 4, trim_in: 1, speed: 1, volume: 1, scale: 1, fit: 'contain', source: { kind: 'video', id: 1 } }
const document = (): EditDocument => ({ version: 1, width: 1280, height: 720, fps: 24, clips: [{ ...video }, { ...video, id: 'v2', start: 4 }] })
const media: EditorMedia = { key: 'video:1', source: video.source, name: 'Video', kind: 'video', duration: 12, url: '/a.mp4' }

describe('typed editor commands', () => {
  it('inserts after the selected video and ripples later layers without mutating the original', () => {
    const original = document(), [result, id] = addMedia(original, media, 0, 'v')
    expect(original.clips).toHaveLength(2)
    expect(result.clips.find(c => c.id === id)?.start).toBe(4)
    expect(result.clips.find(c => c.id === 'v2')?.start).toBe(16)
  })
  it('splits at a frame and translates the next source in-point using speed', () => {
    const original = document(); (original.clips[0] as VideoClip).speed = 2
    const [result, id] = splitClip(original, 'v', 1)
    expect(result.clips.find(c => c.id === 'v')?.duration).toBe(1)
    expect(result.clips.find(c => c.id === id)).toMatchObject({ duration: 3, trim_in: 3, start: 1 })
    expect(() => splitClip(original, 'v', 0)).toThrow()
  })
  it('ripple trims subsequent shots but refuses overlapping moves or invalid source ranges', () => {
    const result = trimClip(document(), 'v', 1, 3, 1, media)
    expect(result.clips[0]?.duration).toBe(2)
    expect(result.clips[1]?.start).toBe(2)
    expect(() => moveClip(document(), 'v2', 3)).toThrow()
    expect(() => changeClip(document(), 'v', { duration: 13 }, media)).toThrow()
  })
  it('duplicates source references without changing source files', () => {
    const [result, id] = duplicateClip(document(), 'v')
    expect(result.clips.find(c => c.id === id)).toMatchObject({ source: { kind: 'video', id: 1 }, start: 4 })
    expect(result.clips.find(c => c.id === 'v2')?.start).toBe(8)
  })
  it('parses SRT timestamps and plain text while refusing malformed intervals', () => {
    const value = parseSrt('1\r\n00:00:01,000 --> 00:00:03,000\r\n修仙 Hello <b>world</b>', document())
    expect(value[0]).toMatchObject({ start: 1, duration: 2, text: '修仙 Hello <b>world</b>' })
    for (const raw of ['00:61:01,000 --> 00:00:03,000\nx', '1\n00:00:03,000 --> 00:00:01,000\nx', 'nothing']) expect(() => parseSrt(raw, document())).toThrow()
  })
  it('wraps long subtitles consistently with output reference coordinates', () => {
    const [result, id] = addSubtitle(document(), 0, '你好世界你好')
    const clip = result.clips.find(c => c.id === id) as SubtitleClip
    expect(subtitleLines({ ...clip, font_size: 30 }, { ...result, width: 100, height: 720 })).toBe('你好世界\n你好')
  })
  it('applies BGM fade-in and fade-out against the timeline clock', () => {
    const clip: AudioClip = { id: 'a', type: 'audio', name: '', start: 2, duration: 8, trim_in: 0, source: { kind: 'asset', id: 1 }, volume: .6, fade_in: 2, fade_out: 2, loop: true }
    expect(audioVolume(clip, 1)).toBe(0)
    expect(audioVolume(clip, 3)).toBeCloseTo(.3)
    expect(audioVolume(clip, 6)).toBeCloseTo(.6)
    expect(audioVolume(clip, 9)).toBeCloseTo(.3)
  })
})
