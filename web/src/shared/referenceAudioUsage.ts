import { tr } from '@/i18n'
import type { VideoGenerationCapabilities } from '@/types'

export function referenceAudioUsage(durations: Array<number | null>, capabilities: VideoGenerationCapabilities | undefined) {
  const known = durations.filter((duration): duration is number => duration !== null && Number.isFinite(duration))
  const totalDuration = known.reduce((total, duration) => total + Math.max(0, duration), 0)
  let error = ''
  if (capabilities) {
    const minimum = capabilities.reference_audio_duration_min ?? 2
    if (durations.length > capabilities.max_reference_audios) {
      error = tr('参考音频超过 {p0} 个（包含角色和旁白音色）', { p0: capabilities.max_reference_audios })
    } else if (known.some(duration => duration < minimum - 0.001 || duration > capabilities.reference_audio_duration_max + 0.001)) {
      error = tr('单条参考音频需为 {p0}–{p1} 秒', { p0: minimum, p1: capabilities.reference_audio_duration_max })
    } else if (totalDuration > capabilities.reference_audio_total_duration_max + 0.001) {
      error = tr('参考音频总时长超过 {p0} 秒', { p0: capabilities.reference_audio_total_duration_max })
    }
  }
  return { count: durations.length, totalDuration, durationComplete: known.length === durations.length, error }
}
