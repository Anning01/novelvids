import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import VideoThumbnail from './VideoThumbnail.vue'

let reveal: () => void
const disconnect = vi.fn()
const observe = vi.fn()

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('IntersectionObserver', class {
    constructor(callback: IntersectionObserverCallback) {
      reveal = () => callback([{ isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver)
    }
    observe = observe
    disconnect = disconnect
  })
})
afterEach(() => vi.unstubAllGlobals())

describe('VideoThumbnail', () => {
  it('uses an existing poster without fetching video bytes', () => {
    const wrapper = mount(VideoThumbnail, { props: { src: '/clip.mp4', poster: '/poster.webp', alt: 'Shot 1 cover' } })
    reveal()
    expect(wrapper.get('img').attributes('src')).toBe('/poster.webp')
    expect(wrapper.find('video').exists()).toBe(false)
    expect(wrapper.attributes('aria-label')).toBe('Shot 1 cover')
    wrapper.unmount()
  })

  it('loads only visible clips and decodes a paused first frame when a poster is missing', async () => {
    const wrapper = mount(VideoThumbnail, { props: { src: '/clip.mp4' } })
    expect(wrapper.find('video').exists()).toBe(false)
    expect(observe).toHaveBeenCalledOnce()
    reveal()
    await wrapper.vm.$nextTick()
    const video = wrapper.get('video')
    const play = vi.spyOn(video.element, 'play')
    Object.defineProperty(video.element, 'duration', { value: 5, configurable: true })
    await video.trigger('loadedmetadata')
    expect(video.element.currentTime).toBe(.1)
    expect(video.element.muted).toBe(true)
    expect(video.attributes('preload')).toBe('metadata')
    expect(video.element.autoplay).toBe(false)
    expect(video.element.controls).toBe(false)
    expect(play).not.toHaveBeenCalled()
    await video.trigger('seeked')
    expect(video.classes()).toContain('is-ready')
    expect(wrapper.find('.video-thumbnail-spinner').exists()).toBe(false)
    wrapper.unmount()
    expect(disconnect).toHaveBeenCalled()
  })

  it('falls back when a saved poster cannot load, and resets after selecting another video', async () => {
    const wrapper = mount(VideoThumbnail, { props: { src: '/one.mp4', poster: '/expired.webp' } })
    reveal()
    await wrapper.get('img').trigger('error')
    expect(wrapper.get('video').attributes('src')).toBe('/one.mp4')
    await wrapper.get('video').trigger('error')
    expect(wrapper.text()).toContain('封面加载失败')
    expect(wrapper.find('.video-thumbnail-spinner').exists()).toBe(false)
    await wrapper.setProps({ src: '/two.mp4', poster: '' })
    expect(wrapper.get('video').attributes('src')).toBe('/two.mp4')
    expect(wrapper.text()).not.toContain('封面加载失败')
    wrapper.unmount()
  })

  it('handles a very short clip and browsers without visibility observers', async () => {
    vi.stubGlobal('IntersectionObserver', undefined)
    const wrapper = mount(VideoThumbnail, { props: { src: '/short.mp4' } })
    await wrapper.vm.$nextTick()
    const video = wrapper.get('video')
    Object.defineProperty(video.element, 'duration', { value: .08, configurable: true })
    await video.trigger('loadedmetadata')
    expect(video.element.currentTime).toBe(.04)
    await video.trigger('loadeddata')
    expect(video.classes()).toContain('is-ready')
    wrapper.unmount()
  })
})
