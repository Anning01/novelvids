import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import DeferredVideoPlayer from './DeferredVideoPlayer.vue'

describe('DeferredVideoPlayer', () => {
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
