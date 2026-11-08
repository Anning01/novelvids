import type { Video } from '@/types'

const LAST_FRAME_CONTINUITY_TITLES = ['【首帧衔接】', '[First-frame continuity]']
const LAST_FRAME_CONTINUITY_SECTION = /^(?:(?:【首帧衔接】|\[First-frame continuity\])\n[^\n]*|\{"first_frame_reference": [^\n]*\})(?:\n+|$)/u

export function hasLastFrameContinuity(video: Pick<Video, 'metadata'>, nextSceneId?: number) {
  const metadata = video.metadata || {}
  if (!metadata.last_frame_url || !['provider', 'ffmpeg'].includes(String(metadata.last_frame_source))
    || metadata.last_frame_extraction_error || metadata.last_frame_propagation_error) return false
  if (nextSceneId === undefined) return true
  const reference = metadata.last_frame_reference as { type?: string; url?: string } | undefined
  return Number(metadata.last_frame_injected_scene_id) === nextSceneId
    && reference?.type === 'image' && reference.url === metadata.last_frame_url
    && Boolean(metadata.last_frame_prompt_instruction)
}

export function injectLastFrameContinuityInstruction(prompt: string, instruction: string) {
  const normalizedInstruction = instruction.trim()
  const body = prompt.trim().replace(LAST_FRAME_CONTINUITY_SECTION, '').trim()
  if (!LAST_FRAME_CONTINUITY_TITLES.some(title => normalizedInstruction.startsWith(`${title}\n`))) return body
  return body ? `${normalizedInstruction}\n\n${body}` : normalizedInstruction
}

export function rebaseLastFrameContinuity(basePrompt: string | null, draftPrompt: string, savedPrompt: string | null | undefined, instruction: string) {
  if (!LAST_FRAME_CONTINUITY_TITLES.some(title => instruction.trim().startsWith(`${title}\n`))) return null
  // Only the known automatic prefix may change; never accept unrelated remote edits as the draft's base.
  if (savedPrompt !== injectLastFrameContinuityInstruction(basePrompt || '', instruction)) return null
  return { basePrompt: savedPrompt, prompt: injectLastFrameContinuityInstruction(draftPrompt, instruction) }
}
