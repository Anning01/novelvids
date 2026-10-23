import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import DeferredVideoPlayer from './DeferredVideoPlayer.vue'

describe('DeferredVideoPlayer', () => {
  it('pauses an activated preview when its chapter or phase becomes hidden without losing the player', async () => {
    const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
    const pause = vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined)
    const wrapper = mount(DeferredVideoPlayer, { props: { src: '/local/result.mp4', title: '本地镜头', autoplayOnActivate: false } })
    await wrapper.get('button').trigger('click')
    const video = wrapper.get('video').element
    expect(play).not.toHaveBeenCalled()
    await wrapper.setProps({ suspended: true })
    expect(pause).toHaveBeenCalledOnce()
    await wrapper.setProps({ suspended: false })
    expect(wrapper.get('video').element).toBe(video)
    expect(play).not.toHaveBeenCalled()
    wrapper.unmount(); play.mockRestore(); pause.mockRestore()
  })
  it('does not create a video request until the user activates playback', async () => {
    const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
    const wrapper = mount(DeferredVideoPlayer, {
      props: {
        src: '/media/videos/9.mp4',
        poster: '/media/videos/posters/9-preview.webp',
        title: '分镜 9',
      },
    })

    expect(wrapper.find('video').exists()).toBe(false)
    expect(wrapper.get('img').attributes('src')).toContain('9-preview.webp')
    await wrapper.get('button').trigger('click')
    expect(wrapper.get('video').attributes('src')).toBe('/media/videos/9.mp4')
    expect(play).toHaveBeenCalledOnce()
    play.mockRestore()
  })
})
