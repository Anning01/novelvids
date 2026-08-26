import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AudioRangeSlider from './AudioRangeSlider.vue'

afterEach(() => vi.restoreAllMocks())

describe('AudioRangeSlider', () => {
  it('使用两个滑块更新裁剪区间并限制片段为1至30秒', async () => {
    const wrapper = mount(AudioRangeSlider, {
      props: { start: 0, end: 30, duration: 60 },
    })
    const sliders = wrapper.findAll<HTMLInputElement>('input[type="range"]')

    expect(sliders).toHaveLength(2)
    expect(wrapper.find('input[type="number"]').exists()).toBe(false)
    await sliders[0]!.setValue('12.4')
    expect(wrapper.emitted('update:start')?.at(-1)).toEqual([12.4])
    await sliders[1]!.setValue('55')
    expect(wrapper.emitted('update:end')?.at(-1)).toEqual([30])
  })

  it('播放时从裁剪起点开始并在裁剪终点停止', async () => {
    const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
    const pause = vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined)
    const wrapper = mount(AudioRangeSlider, {
      props: { src: '/voice.wav', start: 2.5, end: 5, duration: 10 },
    })
    const audio = wrapper.get<HTMLAudioElement>('audio').element

    await wrapper.get('button[aria-label="从裁剪起点播放"]').trigger('click')
    expect(audio.currentTime).toBe(2.5)
    expect(play).toHaveBeenCalledOnce()

    audio.currentTime = 5
    await wrapper.get('audio').trigger('timeupdate')
    expect(pause).toHaveBeenCalled()
    expect(audio.currentTime).toBe(5)
  })
})
