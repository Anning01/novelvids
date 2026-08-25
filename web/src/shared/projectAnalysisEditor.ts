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
  projectType: string
  projectSetting: string
  storyboardStrategy: string
  storyboardSetting: string
}

export interface ChapterEditDraft {
  id: number
  name: string
  content: string
}

type EditableNovel = Pick<
  Novel,
  | 'name'
  | 'tags'
  | 'story_outline'
  | 'project_type'
  | 'project_setting'
  | 'storyboard_strategy'
  | 'storyboard_setting'
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
    tagsText: tags.join('，'),
    storyOutline: novel.story_outline ?? analysis?.story_outline ?? '',
    projectType: novel.project_type ?? DEFAULT_PROJECT_TYPE,
    projectSetting: novel.project_setting ?? DEFAULT_PROJECT_SETTING,
    storyboardStrategy: strategy?.key ?? novel.storyboard_strategy?.trim() ?? DEFAULT_STORYBOARD_STRATEGY,
    storyboardSetting: strategy?.description ?? novel.storyboard_setting ?? '',
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

export function projectPatchFromDraft(draft: ProjectAnalysisDraft): Partial<Novel> {
  return {
    name: draft.name.trim(),
    tags: normalizeTags(draft.tagsText),
    story_outline: draft.storyOutline.trim(),
    project_type: draft.projectType.trim(),
    project_setting: draft.projectSetting.trim(),
    storyboard_strategy: draft.storyboardStrategy.trim(),
    storyboard_setting: draft.storyboardSetting.trim(),
  }
}

export function createChapterEditDraft(chapter: Chapter): ChapterEditDraft {
  return {
    id: chapter.id,
    name: stripChapterOrdinal(chapter.name) || '未命名',
    content: chapter.content ?? '',
  }
}

export function chapterDraftChanged(draft: ChapterEditDraft, chapter: Chapter): boolean {
  return draft.name !== (stripChapterOrdinal(chapter.name) || '未命名') || draft.content !== (chapter.content ?? '')
}
