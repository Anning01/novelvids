import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import BufferedVideoPlayer from './BufferedVideoPlayer.vue'

let paused: WeakMap<HTMLMediaElement, boolean>
let ready: WeakMap<HTMLMediaElement, number>
let failPlay = false

beforeEach(() => {
  paused = new WeakMap(); ready = new WeakMap(); failPlay = false
  vi.spyOn(HTMLMediaElement.prototype, 'readyState', 'get').mockImplementation(function (this: HTMLMediaElement) { return ready.get(this) ?? 4 })
  vi.spyOn(HTMLMediaElement.prototype, 'duration', 'get').mockReturnValue(3)
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {})
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(function (this: HTMLMediaElement) {
    paused.set(this, true); this.dispatchEvent(new Event('pause'))
  })
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(function (this: HTMLMediaElement) {
    if (failPlay) return Promise.reject(new DOMException('Blocked playback', 'NotAllowedError'))
    paused.set(this, false); this.dispatchEvent(new Event('play'))
    this.dispatchEvent(new Event('playing'))
    return Promise.resolve()
  })
})
afterEach(() => vi.restoreAllMocks())
const initial = { src: '/a.mp4', nextSrc: '/b.mp4', title: '分镜视频' }

it('prepares just the current and next videos, retaining both DOM elements across transitions', async () => {
  const wrapper = mount(BufferedVideoPlayer, { props: initial })
  await flushPromises(); await wrapper.vm.start()
  const a = wrapper.get('video[src="/a.mp4"]').element
  const b = wrapper.get('video[src="/b.mp4"]').element
  expect(wrapper.findAll('video')).toHaveLength(2)
  expect(b.getAttribute('preload')).toBe('auto')
  expect((b as HTMLVideoElement).muted).toBe(true)
  await wrapper.setProps({ src: '/b.mp4', nextSrc: '/c.mp4' })
  await wrapper.vm.start(); await flushPromises()
  expect(wrapper.get('video[src="/b.mp4"]').element).toBe(b)
  expect(wrapper.get('video.is-visible').element).toBe(b)
  expect(wrapper.get('video[src="/c.mp4"]').element).toBe(a)
  expect(paused.get(a as HTMLMediaElement)).toBe(true)
  wrapper.unmount()
})

it('holds the previous frame while the incoming clip is unready, then reveals the ready frame', async () => {
  const wrapper = mount(BufferedVideoPlayer, { props: initial })
  await flushPromises(); await wrapper.vm.start()
  const a = wrapper.get('video[src="/a.mp4"]').element as HTMLVideoElement
  const b = wrapper.get('video[src="/b.mp4"]').element as HTMLVideoElement
  ready.set(b, 0)
  await wrapper.setProps({ src: '/b.mp4', nextSrc: '/c.mp4' })
  const play = wrapper.vm.start()
  await flushPromises()
  expect(wrapper.get('video.is-visible').element).toBe(a)
  expect(wrapper.find('[role="status"]').text()).toContain('正在缓冲视频')
  expect(wrapper.find('video[src="/c.mp4"]').exists()).toBe(false)
  ready.set(b, 4); b.dispatchEvent(new Event('loadedmetadata'))
  await play; await flushPromises()
  expect(wrapper.get('video.is-visible').element).toBe(b)
  expect(wrapper.find('[role="status"]').exists()).toBe(false)
  expect(wrapper.find('video[src="/c.mp4"]').exists()).toBe(true)
  wrapper.unmount()
})

it('keeps pause, audio, speed and seeking isolated from the hidden preloader', async () => {
  const wrapper = mount(BufferedVideoPlayer, { props: { ...initial, playbackRate: 1.5 } })
  await flushPromises(); await wrapper.vm.start(1.2, false)
  const a = wrapper.get('video[src="/a.mp4"]').element as HTMLVideoElement
  const b = wrapper.get('video[src="/b.mp4"]').element as HTMLVideoElement
  expect(a.currentTime).toBe(1.2)
  expect(a.playbackRate).toBe(1.5)
  expect(a.muted).toBe(false)
  expect(b.muted).toBe(true)
  expect(paused.get(b) ?? true).toBe(true)
  expect(wrapper.emitted('play')).toBeUndefined()
  await wrapper.setProps({ muted: true, playbackRate: 2 })
  expect(a.muted).toBe(true)
  expect(a.playbackRate).toBe(2)
  await wrapper.vm.start(1.2)
  a.currentTime = 1.4; a.dispatchEvent(new Event('timeupdate'))
  expect(wrapper.emitted('timeupdate')?.at(-1)).toEqual([1.4])
  b.currentTime = 2; b.dispatchEvent(new Event('timeupdate')); b.dispatchEvent(new Event('ended'))
  expect(wrapper.emitted('timeupdate')?.at(-1)).toEqual([1.4])
  expect(wrapper.emitted('ended')).toBeUndefined()
  wrapper.vm.pause()
  expect(paused.get(a)).toBe(true)
  wrapper.unmount()
})

it('cancels metadata listeners so a late response cannot resume playback after pause or navigation', async () => {
  const wrapper = mount(BufferedVideoPlayer, { props: initial })
  const a = wrapper.get('video[src="/a.mp4"]').element as HTMLVideoElement
  ready.set(a, 0)
  const pending = wrapper.vm.start().catch(error => error)
  await flushPromises(); wrapper.vm.pause()
  expect((await pending).name).toBe('AbortError')
  ready.set(a, 4); a.dispatchEvent(new Event('loadedmetadata')); await flushPromises()
  expect(a.play).not.toHaveBeenCalled()
  expect(wrapper.find('[role="status"]').exists()).toBe(false)
  ready.set(a, 0)
  const leaving = wrapper.vm.start().catch(error => error)
  await flushPromises(); wrapper.unmount()
  expect((await leaving).name).toBe('AbortError')
  expect(a.getAttribute('src')).toBeNull()
})

it('does not surface a background preload error until that clip is requested', async () => {
  const wrapper = mount(BufferedVideoPlayer, { props: initial })
  await flushPromises(); await wrapper.vm.start()
  const b = wrapper.get('video[src="/b.mp4"]')
  await b.trigger('error')
  expect(wrapper.emitted('error')).toBeUndefined()
  ready.set(b.element as HTMLVideoElement, 0)
  await wrapper.setProps({ src: '/b.mp4', nextSrc: '' })
  const pending = wrapper.vm.start().catch(error => error)
  await flushPromises(); await b.trigger('error')
  expect((await pending).message).toContain('Video could not be loaded')
  expect(wrapper.emitted('error')).toHaveLength(1)
  expect(wrapper.find('[role="status"]').exists()).toBe(false)
  wrapper.unmount()
})

it('clears buffering after browser playback rejection and permits an explicit retry', async () => {
  const wrapper = mount(BufferedVideoPlayer, { props: initial })
  failPlay = true
  await expect(wrapper.vm.start()).rejects.toMatchObject({ name: 'NotAllowedError' })
  await flushPromises()
  expect(wrapper.find('[role="status"]').exists()).toBe(false)
  failPlay = false
  await wrapper.vm.start(); await flushPromises()
  expect(wrapper.get('video.is-visible').attributes('src')).toBe('/a.mp4')
  wrapper.unmount()
})

it('reloads a failed media source when the user explicitly retries playback', async () => {
  const wrapper = mount(BufferedVideoPlayer, { props: initial })
  await flushPromises()
  const video = wrapper.get('video[src="/a.mp4"]').element as HTMLVideoElement
  let failed = true
  Object.defineProperty(video, 'error', { configurable: true, get: () => failed ? { code: 2 } as MediaError : null })
  vi.mocked(video.load).mockImplementation(() => { failed = false; ready.set(video, 0) })
  const retry = wrapper.vm.start()
  await flushPromises()
  expect(video.load).toHaveBeenCalledTimes(1)
  ready.set(video, 4); video.dispatchEvent(new Event('loadedmetadata'))
  await retry; await flushPromises()
  expect(paused.get(video)).toBe(false)
  expect(wrapper.find('[role="status"]').exists()).toBe(false)
  wrapper.unmount()
})

it('keeps the preloaded following clip through a deliberate black gap', async () => {
  const wrapper = mount(BufferedVideoPlayer, { props: initial })
  await flushPromises(); await wrapper.vm.start()
  const b = wrapper.get('video[src="/b.mp4"]').element
  await wrapper.setProps({ src: '', nextSrc: '/b.mp4' })
  expect(wrapper.find('video.is-visible').exists()).toBe(false)
  expect(wrapper.get('video[src="/b.mp4"]').element).toBe(b)
  await wrapper.setProps({ src: '/b.mp4', nextSrc: '' })
  await wrapper.vm.start()
  expect(wrapper.get('video[src="/b.mp4"]').element).toBe(b)
  wrapper.unmount()
})

it('ignores the old metadata arrival after jumping to an unbuffered clip', async () => {
  const wrapper = mount(BufferedVideoPlayer, { props: initial })
  await flushPromises(); await wrapper.vm.start()
  const b = wrapper.get('video[src="/b.mp4"]').element as HTMLVideoElement
  ready.set(b, 0)
  await wrapper.setProps({ src: '/b.mp4', nextSrc: '/c.mp4' })
  const oldRequest = wrapper.vm.start().catch(error => error)
  await flushPromises()
  await wrapper.setProps({ src: '/d.mp4', nextSrc: '/e.mp4' })
  const d = wrapper.get('video[src="/d.mp4"]').element as HTMLVideoElement
  ready.set(d, 4)
  await wrapper.vm.start(.5); await flushPromises()
  expect((await oldRequest).name).toBe('AbortError')
  const playCount = vi.mocked(d.play).mock.calls.length
  b.dispatchEvent(new Event('loadedmetadata')); await flushPromises()
  expect(wrapper.get('video.is-visible').attributes('src')).toBe('/d.mp4')
  expect(d.play).toHaveBeenCalledTimes(playCount)
  wrapper.unmount()
})
