import { describe, expect, it } from 'vitest'
import { addMedia, addSubtitle, audioVolume, changeClip, duplicateClip, pasteClip, resizeClip, moveClip, orderedVideos, parseSrt, splitClip, subtitleLines, trimClip, videoPlaybackRate, videoSourceEnd } from './model'
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
  it('ripple trims subsequent shots and validates source ranges', () => {
    const result = trimClip(document(), 'v', 1, 3, 1, media)
    expect(result.clips[0]?.duration).toBe(2)
    expect(result.clips[1]?.start).toBe(2)
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

it('pastes a copied music snapshot at the playhead with independent IDs and source objects', () => {
  const music: AudioClip = { id:'music', type:'audio', name:'Music', start:0, duration:47, trim_in:2, source:{kind:'asset',id:9}, volume:.6, fade_in:1, fade_out:2, loop:false }
  const original = document()
  const [result, id] = pasteClip(original, music, 47)
  expect(result.clips.find(clip=>clip.id===id)).toEqual({...music,id,start:47})
  expect(original.clips).toHaveLength(2)
  const pasted = result.clips.find(clip=>clip.id===id) as AudioClip
  pasted.source.id=10
  expect(music.source.id).toBe(9)
  const [again, nextId] = duplicateClip(result,id)
  expect(nextId).not.toBe(id)
  expect(again.clips.find(clip=>clip.id===nextId)?.start).toBe(94)
})
it('snaps pasted videos to a boundary and closes gaps even when pasted past the end', () => {
  const original=document()
  const [result,id]=pasteClip(original,video,4)
  expect(result.clips.find(clip=>clip.id===id)).toMatchObject({start:4,trim_in:1})
  expect(result.clips.find(clip=>clip.id==='v2')?.start).toBe(8)
  const [snapped, snappedId] = pasteClip(original, video, 1)
  expect(orderedVideos(snapped).map(clip => [clip.id, clip.start])).toEqual([[snappedId, 0], ['v', 4], ['v2', 8]])
  const [appended, appendedId] = pasteClip(original, video, 99)
  expect(orderedVideos(appended).at(-1)).toMatchObject({ id: appendedId, start: 8 })
  expect(original.clips[1]?.start).toBe(4)
})

it('keeps duplicates adjacent for imported clips whose duration is not a whole number of frames', () => {
  const original=document()
  original.clips[0]!.duration=4.01
  original.clips[1]!.start=4.01
  const [result,id]=duplicateClip(original,'v')
  expect(result.clips.find(clip=>clip.id===id)?.start).toBe(4.01)
  expect(result.clips.find(clip=>clip.id==='v2')?.start).toBeCloseTo(8.02)
})

it('uses the same frame-aligned resize for previews and commits and validates source bounds', () => {
  const original=document()
  const clip=original.clips[0] as VideoClip
  clip.speed=2
  const result=resizeClip(original,'v','left',1,media)
  expect(result.clips[0]).toMatchObject({start:0,duration:3,trim_in:3,speed:2})
  expect(original.clips[0]).toMatchObject({start:0,duration:4,trim_in:1})
  expect(result.clips[1]?.start).toBe(3)
  expect(resizeClip(original,'v','right',1,media).clips[1]?.start).toBe(5)
  const single={...original,clips:[original.clips[0]!]}
  expect(()=>resizeClip(single,'v','right',3,media)).toThrow('裁剪范围超过原素材')
})

it('supports the requested dB range and defaults newly added BGM to 0dB without changing old clips',()=>{
 const music:EditorMedia={...media,key:'asset:8',source:{kind:'asset',id:8},kind:'audio'}
 const [result,id]=addMedia(document(),music,0,'')
 expect(result.clips.find(clip=>clip.id===id)).toMatchObject({volume:1})
 const clip:AudioClip={id:'a',type:'audio',name:'',start:0,duration:2,trim_in:0,source:music.source,volume:10,fade_in:1,fade_out:0,loop:false}
 expect(audioVolume(clip,.5)).toBe(5)
 expect(()=>changeClip(document(),'v',{speed:.1,volume:10,rotation:-5})).not.toThrow()
 expect(()=>changeClip(document(),'v',{speed:20})).not.toThrow()
 expect(()=>changeClip(document(),'v',{speed:20.01})).toThrow()
})

it('reorders video on either side without moving independently timed tracks', () => {
  const value = document()
  value.clips.push({ ...video, id: 'v3', start: 8 })
  const [withSubtitle, id] = addSubtitle(value, 3)
  const moved = moveClip(withSubtitle, 'v', 6)
  expect(orderedVideos(moved).map(clip => [clip.id, clip.start])).toEqual([['v2', 0], ['v3', 4], ['v', 8]])
  expect(moved.clips.find(clip => clip.id === id)?.start).toBe(3)
  expect(orderedVideos(moveClip(moved, 'v', -10)).map(clip => [clip.id, clip.start])).toEqual([['v', 0], ['v2', 4], ['v3', 8]])
})

it('preserves the exact source range through repeated speed changes and keeps videos touching', () => {
  const value = document()
  value.clips = [{ ...video, start: 0, trim_in: 0, duration: 8 }, { ...video, id: 'v2', start: 8 }]
  const source = { ...media, duration: 8 }
  let updated = value
  for (const speed of [2.82, 8.74, 20, .1, 1]) {
    const current = orderedVideos(updated)[0]!
    updated = trimClip(updated, current.id, current.trim_in, videoSourceEnd(current), speed, source)
    const [first, second] = orderedVideos(updated)
    expect(first?.trim_out).toBe(8)
    expect(first!.duration * videoPlaybackRate(first!)).toBeCloseTo(8)
    expect(second?.start).toBe(first!.duration)
  }
  expect(orderedVideos(updated)[0]?.duration).toBe(8)
})

it('retimes and splits a cropped range without losing either source boundary', () => {
  const [first, second] = orderedVideos(trimClip(document(), 'v', 1, 3.3, 8.74, media))
  expect(first?.trim_out).toBe(3.3)
  expect(second?.start).toBe(first!.duration)
  const retimed = trimClip(document(), 'v', 1, 3.3, 8.74, media)
  const [split, id] = splitClip(retimed, 'v', .125)
  const left = orderedVideos(split)[0]!
  const right = orderedVideos(split).find(clip => clip.id === id)!
  expect(left.trim_out).toBe(right.trim_in)
  expect(right.trim_out).toBe(3.3)
})

it('keeps a very short source visible for one frame at 20×', () => {
  const value = document()
  value.clips = [{ ...video, trim_in: 0, duration: .125 }]
  const clip = orderedVideos(trimClip(value, 'v', 0, .125, 20, { ...media, duration: .125 }))[0]!
  expect(clip.duration).toBe(1 / 24)
  expect(clip.trim_out).toBe(.125)
})
