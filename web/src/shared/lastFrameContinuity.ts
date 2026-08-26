const LAST_FRAME_CONTINUITY_TITLE = '【首帧衔接】'
const LAST_FRAME_CONTINUITY_SECTION = /^【首帧衔接】\n[^\n]*(?:\n+|$)/u

export function injectLastFrameContinuityInstruction(prompt: string, instruction: string) {
  const normalizedInstruction = instruction.trim()
  const body = prompt.trim().replace(LAST_FRAME_CONTINUITY_SECTION, '').trim()
  if (!normalizedInstruction.startsWith(`${LAST_FRAME_CONTINUITY_TITLE}\n`)) return body
  return body ? `${normalizedInstruction}\n\n${body}` : normalizedInstruction
}
