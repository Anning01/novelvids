export const DURATION_MENTION_SOURCE = String.raw`@\{(?:镜头|视频)时长(?::(\d+(?:\.\d+)?)s?)?\}`

export function parseDurationMention(syntax: string): { seconds: number | null } | null {
  const match = new RegExp(`^${DURATION_MENTION_SOURCE}$`).exec(syntax)
  return match ? { seconds: match[1] === undefined ? null : Number(match[1]) } : null
}
