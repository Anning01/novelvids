const LAST_FRAME_CONTINUITY_TITLES = ['【首帧衔接】', '[First-frame continuity]']
const LAST_FRAME_CONTINUITY_SECTION = /^(?:【首帧衔接】|\[First-frame continuity\])\n[^\n]*(?:\n+|$)/u

export function injectLastFrameContinuityInstruction(prompt: string, instruction: string) {
  const normalizedInstruction = instruction.trim()
  const body = prompt.trim().replace(LAST_FRAME_CONTINUITY_SECTION, '').trim()
  if (!LAST_FRAME_CONTINUITY_TITLES.some(title => normalizedInstruction.startsWith(`${title}\n`))) return body
  return body ? `${normalizedInstruction}\n\n${body}` : normalizedInstruction
}
