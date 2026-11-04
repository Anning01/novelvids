import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import EditorPreview from './EditorPreview.vue'
import { editorFixture } from './fixtures'

let callback: FrameRequestCallback | undefined
let paused: WeakMap<HTMLMediaElement, boolean>
beforeEach(() => {
  paused = new WeakMap()
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => { callback = cb; return 1 })
  vi.stubGlobal('cancelAnimationFrame', () => {})
  vi.spyOn(HTMLMediaElement.prototype, 'readyState', 'get').mockReturnValue(4)
  vi.spyOn(HTMLMediaElement.prototype, 'duration', 'get').mockReturnValue(2)
  vi.spyOn(HTMLMediaElement.prototype, 'paused', 'get').mockImplementation(function (this: HTMLMediaElement) { return paused.get(this) ?? true })
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {})
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(function (this: HTMLMediaElement) { paused.set(this, false); this.dispatchEvent(new Event('playing')); return Promise.resolve() })
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(function (this: HTMLMediaElement) { paused.set(this, true) })
})
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('syncs BGM position and fades to the video clock and silences it during buffering', async () => {
  const fixture = editorFixture()
  fixture.document.clips.push({ id: 'a', type: 'audio', name: 'BGM', start: 0, duration: 2, source: { kind: 'asset', id: 9 }, trim_in: 0, volume: .5, fade_in: 1, fade_out: 0, loop: false })
  fixture.media.push({ key: 'asset:9', source: { kind: 'asset', id: 9 }, kind: 'audio', name: 'BGM', duration: 2, url: '/music.wav' })
  const wrapper = mount(EditorPreview, { props: { document: fixture.document, media: fixture.media, time: 0, playing: false, muted: false, selectedId: 'v1' }, global: { stubs: { VideoThumbnail: true } } })
  await wrapper.setProps({ playing: true }); await flushPromises()
  await wrapper.setProps({ time: .5 }); callback?.(100); await flushPromises()
  const audio = wrapper.get('audio').element as HTMLAudioElement
  expect(audio.currentTime).toBeCloseTo(.5)
  expect(audio.volume).toBeCloseTo(.25)
  expect(paused.get(audio)).toBe(false)
  wrapper.get('video[src="/media/clip-1.mp4"]').element.dispatchEvent(new Event('waiting')); await flushPromises()
  expect(paused.get(audio)).toBe(true)
  await wrapper.setProps({ playing: false }); expect(paused.get(audio)).toBe(true)
  wrapper.unmount()
})

it('holds the last real video frame at the episode end instead of showing a new blank gap', () => {
  const fixture = editorFixture()
  const wrapper = mount(EditorPreview, { props: { document: fixture.document, media: fixture.media, time: 6, playing: false, muted: false, selectedId: 'v3' }, global: { stubs: { VideoThumbnail: true } } })
  expect(wrapper.find('.video-stage-blackout').exists()).toBe(false)
  wrapper.unmount()
})

it('presents standalone library audio as a preview rather than an empty timeline error', () => {
  const fixture = editorFixture()
  fixture.document.clips = [{ id: 'a', type: 'audio', name: 'Team music', start: 0, duration: 2, source: { kind: 'library', id: 9 }, trim_in: 0, volume: .5, fade_in: 0, fade_out: 0, loop: false }]
  fixture.media = [{ key: 'library:9', source: { kind: 'library', id: 9 }, kind: 'audio', name: 'Team music', duration: 2, url: '/music.wav' }]
  const wrapper = mount(EditorPreview, { props: { document: fixture.document, media: fixture.media, time: 0, playing: false, muted: false, selectedId: '' } })
  expect(wrapper.get('.editor-audio-preview').text()).toContain('Team music')
  expect(wrapper.text()).not.toContain('时间线空白')
  expect(wrapper.get('audio').attributes('src')).toBe('/music.wav')
  wrapper.unmount()
})
