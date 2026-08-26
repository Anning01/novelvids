import { describe, expect, it } from 'vitest'
import { encodeAudioBufferSlice } from './audioTrim'

describe('本地音频裁剪', () => {
  it('把选定时间段编码为标准 PCM WAV', () => {
    const data = new Float32Array([0, 0.5, -0.5, 1])
    const output = encodeAudioBufferSlice({
      numberOfChannels: 1,
      sampleRate: 2,
      length: data.length,
      getChannelData: () => data,
    }, 0.5, 1.5)
    const view = new DataView(output)

    expect(new TextDecoder().decode(output.slice(0, 4))).toBe('RIFF')
    expect(new TextDecoder().decode(output.slice(8, 12))).toBe('WAVE')
    expect(view.getUint32(40, true)).toBe(4)
    expect(view.getInt16(44, true)).toBeGreaterThan(0)
    expect(view.getInt16(46, true)).toBeLessThan(0)
  })
})
