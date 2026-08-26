const ASSET_REFERENCE_TITLE = '【角色 / 道具 / 场景引用】'
const VOICE_REFERENCE_LABEL = '角色音色参考：'
const VOICE_REFERENCE_LABEL_PATTERN = /^角色音色参考[：:]/mu
const LEGACY_VOICE_REFERENCE_PATTERN = /(?:^|\n{2,})【音色参考】\n[\s\S]*$/u

export interface VoiceReferenceAsset {
  assetId: number
  name: string
  aliases: string[]
  referenceId: number
}

export interface VoiceReferenceMapping {
  referenceId: number
  kind: 'narrator' | 'character'
  subjects: string[]
}

interface VoiceReferenceContext {
  prompt: string
  promptParams?: Record<string, unknown>
  narratorReferenceId?: number | null
  assets: VoiceReferenceAsset[]
}

function escapePattern(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function hasNarrator(context: VoiceReferenceContext) {
  if (!context.narratorReferenceId || context.narratorReferenceId < 1) return false
  const narration = context.promptParams?.narration
  if (Array.isArray(narration) && narration.some(line => typeof line === 'string' && line.includes('旁白'))) {
    return true
  }
  return context.prompt.includes('旁白（') || context.prompt.includes('旁白：')
}

function characterHasDialogue(prompt: string, asset: VoiceReferenceAsset) {
  return [asset.name, ...asset.aliases].some(name => {
    const escaped = escapePattern(name)
    return new RegExp(`(?:@\\{?${escaped}\\}?|${escaped})\\s*(?:[（(][^\\n）)]*[）)])?\\s*[:：]`, 'u').test(prompt)
  })
}

function firstMention(prompt: string, asset: VoiceReferenceAsset) {
  let match: { index: number; length: number } | null = null
  for (const name of [asset.name, ...asset.aliases]) {
    for (const pattern of [
      new RegExp(`@\\{${escapePattern(name)}(?:#[^}]*)?\\}`, 'gu'),
      new RegExp(`@${escapePattern(name)}`, 'gu'),
    ]) {
      const occurrence = pattern.exec(prompt)
      if (!occurrence) continue
      if (!match || occurrence.index < match.index || (
        occurrence.index === match.index && occurrence[0].length > match.length
      )) {
        match = { index: occurrence.index, length: occurrence[0].length }
      }
    }
  }
  return match
}

export function buildVoiceReferenceMappings(context: VoiceReferenceContext): VoiceReferenceMapping[] {
  const assignments: Array<{ referenceId: number; kind: 'narrator' | 'character'; subject: string }> = []
  if (hasNarrator(context)) {
    assignments.push({
      referenceId: Number(context.narratorReferenceId),
      kind: 'narrator',
      subject: '旁白',
    })
  }

  const mentioned = context.assets
    .flatMap(asset => {
      const occurrence = firstMention(context.prompt, asset)
      return occurrence ? [{ asset, ...occurrence }] : []
    })
    .sort((left, right) => left.index - right.index || right.length - left.length)
  const assignedAssetIds = new Set<number>()
  for (const { asset } of mentioned) {
    if (assignedAssetIds.has(asset.assetId)) continue
    assignedAssetIds.add(asset.assetId)
    assignments.push({
      referenceId: asset.referenceId,
      kind: 'character',
      subject: asset.name,
    })
  }
  for (const asset of context.assets) {
    if (assignedAssetIds.has(asset.assetId) || !characterHasDialogue(context.prompt, asset)) continue
    assignedAssetIds.add(asset.assetId)
    assignments.push({
      referenceId: asset.referenceId,
      kind: 'character',
      subject: asset.name,
    })
  }

  const grouped = new Map<number, VoiceReferenceMapping>()
  for (const assignment of assignments) {
    const current = grouped.get(assignment.referenceId)
    if (!current) {
      grouped.set(assignment.referenceId, {
        referenceId: assignment.referenceId,
        kind: assignment.kind,
        subjects: [assignment.subject],
      })
    } else if (!current.subjects.includes(assignment.subject)) {
      current.subjects.push(assignment.subject)
    }
  }
  return [...grouped.values()]
}

export function renderVoiceReferenceInstruction(mappings: VoiceReferenceMapping[]) {
  if (!mappings.length) return ''
  const lines = [VOICE_REFERENCE_LABEL]
  mappings.forEach((mapping, index) => {
    const target = mapping.kind === 'narrator'
      ? '对应旁白'
      : `对应角色 ${mapping.subjects.map(name => `@{${name}}`).join('、')}`
    const referenceTarget = mapping.kind === 'narrator' ? '旁白' : '对应角色'
    const content = mapping.kind === 'narrator' ? '实际旁白内容' : '实际台词内容'
    lines.push(
      `@音频${index + 1} ${target}；该音频仅用于参考${referenceTarget}的音色、音域、语速和说话质感；` +
      `不得复述样本原话，${content}严格按本镜头提示词生成。`,
    )
  })
  return lines.join('\n')
}

function synchronizeExistingVoiceReferences(
  prompt: string,
  mappings: VoiceReferenceMapping[],
) {
  const lines = prompt.split('\n')
  mappings.forEach((mapping, index) => {
    const number = index + 1
    const lineIndex = lines.findIndex(line => new RegExp(`^(?:\\[音频${number}\\]|@音频${number})(?:\\s|$)`, 'u').test(line.trim()))
    if (lineIndex < 0) return
    const current = lines[lineIndex]!.trim()
      .replace(new RegExp(`^(?:\\[音频${number}\\]|@音频${number})\\s*`, 'u'), '')
    if (current.includes('对应角色') || current.includes('对应旁白')) {
      lines[lineIndex] = `@音频${number} ${current}`
      return
    }
    const target = mapping.kind === 'narrator'
      ? '对应旁白'
      : `对应角色 ${mapping.subjects.map(name => `@{${name}}`).join('、')}`
    const normalized = current
      .replace(/^仅用于参考旁白的/u, '该音频仅用于参考旁白的')
      .replace(/^仅用于参考角色“[^\n”]+”(?:、角色“[^\n”]+”)*的/u, '该音频仅用于参考对应角色的')
    lines[lineIndex] = `@音频${number} ${target}；${normalized}`
  })
  return lines.join('\n')
}

function insertIntoAssetReferenceSection(prompt: string, instruction: string) {
  const lines = prompt.split('\n')
  const sectionIndex = lines.findIndex(line => line.trim() === ASSET_REFERENCE_TITLE)
  if (sectionIndex < 0) {
    return `${ASSET_REFERENCE_TITLE}\n${instruction}\n\n${prompt}`.trim()
  }

  let sectionEnd = lines.length
  for (let index = sectionIndex + 1; index < lines.length; index += 1) {
    if (/^【[^\n]+】$/u.test(lines[index]?.trim() || '')) {
      sectionEnd = index
      break
    }
  }
  const roleReferenceIndex = lines.findIndex((line, index) => (
    index > sectionIndex
    && index < sectionEnd
    && /^角色参考[：:]/u.test(line.trim())
  ))
  lines.splice(roleReferenceIndex >= 0 ? roleReferenceIndex + 1 : sectionIndex + 1, 0, instruction)
  return lines.join('\n').trim()
}

export function injectEditableVoiceReferenceInstruction(
  prompt: string,
  mappings: VoiceReferenceMapping[],
) {
  const body = prompt.trim()
  if (!mappings.length) return body
  if (VOICE_REFERENCE_LABEL_PATTERN.test(body)) {
    return synchronizeExistingVoiceReferences(body, mappings)
  }
  const instruction = renderVoiceReferenceInstruction(mappings)
  const withoutLegacySection = body.replace(LEGACY_VOICE_REFERENCE_PATTERN, '').trim()
  return insertIntoAssetReferenceSection(withoutLegacySection, instruction)
}
