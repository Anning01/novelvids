const MAX_CLIP_DURATION = 30
const MIN_CLIP_DURATION = 1

function writeAscii(view: DataView, offset: number, value: string) {
  for (let index = 0; index < value.length; index += 1) {
    view.setUint8(offset + index, value.charCodeAt(index))
  }
}

export function encodeAudioBufferSlice(
  buffer: Pick<AudioBuffer, 'numberOfChannels' | 'sampleRate' | 'length' | 'getChannelData'>,
  start: number,
  end: number,
) {
  const startFrame = Math.max(0, Math.floor(start * buffer.sampleRate))
  const endFrame = Math.min(buffer.length, Math.ceil(end * buffer.sampleRate))
  const frameCount = endFrame - startFrame
  if (frameCount <= 0) throw new Error('裁剪范围无效')
  const channels = Math.max(1, buffer.numberOfChannels)
  const bytesPerSample = 2
  const dataSize = frameCount * channels * bytesPerSample
  const output = new ArrayBuffer(44 + dataSize)
  const view = new DataView(output)
  writeAscii(view, 0, 'RIFF')
  view.setUint32(4, 36 + dataSize, true)
  writeAscii(view, 8, 'WAVE')
  writeAscii(view, 12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, channels, true)
  view.setUint32(24, buffer.sampleRate, true)
  view.setUint32(28, buffer.sampleRate * channels * bytesPerSample, true)
  view.setUint16(32, channels * bytesPerSample, true)
  view.setUint16(34, 16, true)
  writeAscii(view, 36, 'data')
  view.setUint32(40, dataSize, true)

  const channelData = Array.from({ length: channels }, (_, channel) => buffer.getChannelData(channel))
  let offset = 44
  for (let frame = startFrame; frame < endFrame; frame += 1) {
    for (let channel = 0; channel < channels; channel += 1) {
      const sample = Math.max(-1, Math.min(1, channelData[channel]?.[frame] || 0))
      view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true)
      offset += bytesPerSample
    }
  }
  return output
}

export async function trimLocalAudioFile(file: File, start: number, end: number) {
  const duration = end - start
  if (start < 0 || duration < MIN_CLIP_DURATION || duration > MAX_CLIP_DURATION) {
    throw new Error('裁剪片段必须为 1-30 秒')
  }
  const AudioContextConstructor = window.AudioContext
  if (!AudioContextConstructor) throw new Error('当前浏览器不支持在线音频裁剪')
  const context = new AudioContextConstructor()
  try {
    const buffer = await context.decodeAudioData(await file.arrayBuffer())
    if (end > buffer.duration + 0.05) throw new Error('裁剪范围超出原音频时长')
    const wav = encodeAudioBufferSlice(buffer, start, end)
    const baseName = file.name.replace(/\.(mp3|wav)$/i, '') || '音色'
    return new File([wav], `${baseName}-裁剪.wav`, { type: 'audio/wav' })
  } finally {
    await context.close()
  }
}
