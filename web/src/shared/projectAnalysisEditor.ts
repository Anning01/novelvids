
import { tr } from '@/i18n'
import type { Chapter, Novel, StoryboardStrategy } from '@/types'
import { stripChapterOrdinal } from './chapterTitle'

export const DEFAULT_PROJECT_TYPE = 'AI 精品短剧'
export const DEFAULT_PROJECT_SETTING = '自动理解完整剧本，规划分集节奏、人物关系与视觉生产流程。'
export const DEFAULT_STORYBOARD_STRATEGY = 'cinematic'
export const LEGACY_CINEMATIC_STORYBOARD_STRATEGIES = ['电影化叙事 1.5', '电影化叙事', '电影感叙事']

export interface AnalysisSummary {
  book_types?: string[]
  story_outline?: string
}

export interface ProjectAnalysisDraft {
  name: string
  tagsText: string
  storyOutline: string
  styleKey?: string
  customStyle?: string
  audiovisualGuidance?: string
  storyboardEnabled?: boolean
  shotDurationMax?: number
  projectType: string
  projectSetting: string
  storyboardStrategy: string
  storyboardSetting: string
  narratorAudioReferenceId?: number | null
}

export interface ChapterEditDraft {
  id: number
  name: string
  content: string
  screenplay?: string
}

type EditableNovel = Pick<
  Novel,
  | 'shot_duration_max' | 'style_key' | 'custom_style_prompt' | 'audiovisual_guidance' | 'storyboard_enabled'
  | 'name'
  | 'tags'
  | 'story_outline'
  | 'project_type'
  | 'project_setting'
  | 'storyboard_strategy'
  | 'storyboard_setting'
  | 'narrator_audio_reference_id'
>

export function normalizeTags(value: string): string[] {
  return [...new Set(
    value
      .split(/[,，、\n]+/)
      .map(tag => tag.trim())
      .filter(Boolean),
  )].slice(0, 30)
}

export function createProjectAnalysisDraft(
  novel: EditableNovel,
  analysis?: AnalysisSummary | null,
  strategies: StoryboardStrategy[] = [],
): ProjectAnalysisDraft {
  const tags = novel.tags ?? analysis?.book_types ?? []
  const strategy = resolveStoryboardStrategy(novel.storyboard_strategy, strategies)
  return {
    name: novel.name,
    styleKey: novel.custom_style_prompt ? 'custom' : novel.style_key || 'auto',
    customStyle: novel.custom_style_prompt || '',
    audiovisualGuidance: novel.audiovisual_guidance || '',
    storyboardEnabled: novel.storyboard_enabled ?? false,
    shotDurationMax: novel.shot_duration_max ?? 15,
    tagsText: tags.join('，'),
    storyOutline: novel.story_outline ?? analysis?.story_outline ?? '',
    projectType: novel.project_type ?? tr(DEFAULT_PROJECT_TYPE),
    projectSetting: novel.project_setting ?? tr(DEFAULT_PROJECT_SETTING),
    storyboardStrategy: strategy?.key ?? novel.storyboard_strategy?.trim() ?? DEFAULT_STORYBOARD_STRATEGY,
    storyboardSetting: strategy?.description ?? novel.storyboard_setting ?? '',
    narratorAudioReferenceId: novel.narrator_audio_reference_id ?? null,
  }
}

export function resolveStoryboardStrategy(
  value: string | null | undefined,
  strategies: StoryboardStrategy[],
): StoryboardStrategy | undefined {
  const normalized = value?.trim() || DEFAULT_STORYBOARD_STRATEGY
  const lookup = LEGACY_CINEMATIC_STORYBOARD_STRATEGIES.includes(normalized)
    ? DEFAULT_STORYBOARD_STRATEGY
    : normalized
  return strategies.find(strategy => strategy.key === lookup || strategy.name === lookup)
    ?? strategies.find(strategy => strategy.is_default)
    ?? strategies.find(strategy => strategy.key === DEFAULT_STORYBOARD_STRATEGY)
}

export function projectPatchFromDraft(
  draft: ProjectAnalysisDraft,
  initial?: ProjectAnalysisDraft | null,
): Partial<Novel> {
  const settings: Partial<Novel> = {}
  if (draft.styleKey && (draft.styleKey !== initial?.styleKey ||
      (draft.styleKey === 'custom' && draft.customStyle !== initial?.customStyle))) {
    settings.style_key = ['auto', 'custom'].includes(draft.styleKey) ? null : draft.styleKey
    settings.custom_style_prompt = draft.styleKey === 'custom' ? draft.customStyle?.trim() : null
  }
  if (draft.audiovisualGuidance !== initial?.audiovisualGuidance) settings.audiovisual_guidance = draft.audiovisualGuidance?.trim() || null
  if (draft.shotDurationMax !== initial?.shotDurationMax) settings.shot_duration_max = draft.shotDurationMax
  if (draft.storyboardEnabled !== initial?.storyboardEnabled) settings.storyboard_enabled = draft.storyboardEnabled
  if (!initial) {
    return {
      ...settings,
      name: draft.name.trim(),
      tags: normalizeTags(draft.tagsText),
      story_outline: draft.storyOutline.trim(),
      project_type: draft.projectType.trim(),
      project_setting: draft.projectSetting.trim(),
      storyboard_strategy: draft.storyboardStrategy.trim(),
      storyboard_setting: draft.storyboardSetting.trim(),
      ...('narratorAudioReferenceId' in draft
        ? { narrator_audio_reference_id: draft.narratorAudioReferenceId ?? null }
        : {}),
    }
  }

  const patch: Partial<Novel> = settings
  const nextName = draft.name.trim()
  if (nextName !== initial.name.trim()) {
    patch.name = nextName
  }

  const nextTags = normalizeTags(draft.tagsText)
  const initialTags = normalizeTags(initial.tagsText)
  if (nextTags.length !== initialTags.length || nextTags.some((tag, idx) => tag !== initialTags[idx])) {
    patch.tags = nextTags
  }

  const nextOutline = draft.storyOutline.trim()
  if (nextOutline !== initial.storyOutline.trim()) {
    patch.story_outline = nextOutline
  }

  const nextProjectType = draft.projectType.trim()
  if (nextProjectType !== initial.projectType.trim()) {
    patch.project_type = nextProjectType
  }

  const nextProjectSetting = draft.projectSetting.trim()
  if (nextProjectSetting !== initial.projectSetting.trim()) {
    patch.project_setting = nextProjectSetting
  }

  const nextStoryboardStrategy = draft.storyboardStrategy.trim()
  if (nextStoryboardStrategy !== initial.storyboardStrategy.trim()) {
    patch.storyboard_strategy = nextStoryboardStrategy
  }

  const nextStoryboardSetting = draft.storyboardSetting.trim()
  if (nextStoryboardSetting !== initial.storyboardSetting.trim()) {
    patch.storyboard_setting = nextStoryboardSetting
  }

  const nextNarrator = draft.narratorAudioReferenceId ?? null
  const initialNarrator = initial.narratorAudioReferenceId ?? null
  if (nextNarrator !== initialNarrator) {
    patch.narrator_audio_reference_id = nextNarrator
  }

  return patch
}

export function createChapterEditDraft(chapter: Chapter): ChapterEditDraft {
  return {
    id: chapter.id,
    name: stripChapterOrdinal(chapter.name) || tr('未命名'),
    content: chapter.content ?? '',
    screenplay: chapter.screenplay ?? '',
  }
}

export function chapterDraftChanged(draft: ChapterEditDraft, chapter: Chapter): boolean {
  return draft.name !== (stripChapterOrdinal(chapter.name) || '未命名') || draft.content !== (chapter.content ?? '') || (draft.screenplay ?? '') !== (chapter.screenplay ?? '')
}
