import { describe, expect, it } from 'vitest'
import {
  chapterDraftChanged,
  createChapterEditDraft,
  createProjectAnalysisDraft,
  normalizeTags,
  projectPatchFromDraft,
} from './projectAnalysisEditor'

describe('project analysis editor', () => {
  it('uses persisted empty values instead of reviving AI fallback content', () => {
    const draft = createProjectAnalysisDraft(
      {
        name: '项目',
        tags: [],
        story_outline: '',
        project_type: '',
        project_setting: '',
        storyboard_strategy: '',
        storyboard_setting: '',
      },
      { book_types: ['AI 标签'], story_outline: 'AI 大纲' },
    )

    expect(draft.tagsText).toBe('')
    expect(draft.storyOutline).toBe('')
    expect(draft.projectType).toBe('')
  })

  it('normalizes tags and builds the novel patch payload', () => {
    expect(normalizeTags('都市，成长, 都市\n热血')).toEqual(['都市', '成长', '热血'])

    expect(projectPatchFromDraft({
      name: '  新昵称  ',
      tagsText: '都市，成长',
      storyOutline: '  新大纲  ',
      projectType: ' 精品短剧 ',
      projectSetting: ' 项目说明 ',
      storyboardStrategy: ' 快节奏 ',
      storyboardSetting: ' 分镜说明 ',
    })).toEqual({
      name: '新昵称',
      tags: ['都市', '成长'],
      story_outline: '新大纲',
      project_type: '精品短剧',
      project_setting: '项目说明',
      storyboard_strategy: '快节奏',
      storyboard_setting: '分镜说明',
    })
  })

  it('detects chapter title and content changes', () => {
    const chapter = {
      id: 8,
      novel_id: 1,
      number: 2,
      name: '第二章',
      content: '正文',
      created_at: '',
      updated_at: '',
    }
    const draft = createChapterEditDraft(chapter)

    expect(draft.name).toBe('未命名')
    expect(chapterDraftChanged(draft, chapter)).toBe(false)
    draft.content = '修改后的正文'
    expect(chapterDraftChanged(draft, chapter)).toBe(true)
  })
})
