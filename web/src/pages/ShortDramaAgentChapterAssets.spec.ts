import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '@/api'
import ImageModelSelect from '@/components/ImageModelSelect.vue'
import AppButton from '@/components/AppButton.vue'
import { AssetTypeEnum, TaskStatusEnum, type Novel } from '@/types'
import ShortDramaAgentPage from './ShortDramaAgentPage.vue'
import { useCreationAgentWorkspace } from '@/features/creation-agent/workspace'
import { useAuthStore } from '@/features/auth/authStore'

const push = vi.fn()
const replace = vi.fn()

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { projectId: '9' }, query: { chapter: '2162' } }),
  useRouter: () => ({ push, replace, back: vi.fn() }),
}))

vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      configs: vi.fn(),
      remakeCapabilities: vi.fn(),
      novel: vi.fn(),
      novelMeta: vi.fn(),
      novelAnalysis: vi.fn(),
      chapters: vi.fn(),
      chaptersPage: vi.fn(),
      chapter: vi.fn(),
      assets: vi.fn(),
      storyboardStrategies: vi.fn(),
      analyzeNovel: vi.fn(),
      generateNovelCover: vi.fn(),
      imageGenerationModels: vi.fn(),
      generateScreenplay: vi.fn(),
      task: vi.fn(),
      updateNovel: vi.fn(),
      updateChapter: vi.fn(),
    },
  }
})

const chapter = {
  id: 2162,
  novel_id: 9,
  number: 1,
  name: '厄运之手',
  content: '宫平与运在雨中前行。',
  created_at: '2026-08-06T00:00:00.000Z',
  updated_at: '2026-08-06T00:00:00.000Z',
}

let pinia: ReturnType<typeof createPinia>

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  vi.mocked(api.imageGenerationModels).mockResolvedValue({code: 0, message: '', data: []})
  vi.mocked(api.remakeCapabilities).mockResolvedValue({code: 0, message: '', data: {
    media: {extensions: [], max_bytes: 0, max_duration_seconds: 0}, source_modes: {single_upload: true, folder_upload: true, history: true},
    aspect_ratios: ['16:9', '9:16'], resolutions: ['720p', '1080p', '1080P'],
    styles: [{key: 'auto', label: 'AI 识别风格'}, {key: 'xianxia-3d', label: '3D仙侠'}],
  }})
  vi.mocked(api.configs).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: { items: [], pagination: { total: 0, page: 1, page_size: 100, pages: 0 } },
  })
  vi.mocked(api.novelMeta).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: {
      id: 9,
      name: '厄运之手',
      author: 'Agent 创建',
      description: 'Agent 模式 · 9:16 · 720p · 写实通用',
      total_chapters: 1,
      content_length: 200,
      storyboard_strategy: 'narration',
      storyboard_setting: '旁白规则',
      created_at: '2026-08-06T00:00:00.000Z',
      updated_at: '2026-08-06T00:00:00.000Z',
    },
  })
  vi.mocked(api.storyboardStrategies).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: [
      { key: 'cinematic', name: '电影感叙事', description: '原电影感规则', is_default: true },
      { key: 'narration', name: '旁白叙事', description: '旁白规则', is_default: false },
    ],
  })
  vi.mocked(api.novelAnalysis).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: {
      id: 'analysis-task',
      task_type: 3,
      status: TaskStatusEnum.COMPLETED,
      response_data: {
        book_types: ['都市'],
        story_outline: '测试大纲',
        key_characters: [{
          name: '旧人物',
          aliases: [],
          role: '旧标记',
          description: '项目分析阶段的旧人物。',
          base_traits: '',
          chapter_numbers: [1],
        }],
        chapter_count: 1,
        cover: '',
      },
      created_at: '2026-08-06T00:00:00.000Z',
    },
  })
  vi.mocked(api.chaptersPage).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: { items: [chapter], pagination: { total: 1, page: 1, page_size: 30, pages: 1 } },
  })
  vi.mocked(api.chapter).mockResolvedValue({ code: 0, message: 'ok', data: chapter })
  vi.mocked(api.assets).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: {
      items: [
        {
          id: 31,
          novel_id: 9,
          asset_type: AssetTypeEnum.PERSON,
          canonical_name: '宫平',
          source_chapters: [1],
          created_at: '2026-08-06T00:00:00.000Z',
          updated_at: '2026-08-06T00:00:00.000Z',
        },
        {
          id: 32,
          novel_id: 9,
          asset_type: AssetTypeEnum.SCENE,
          canonical_name: '雨夜街道',
          source_chapters: [1],
          created_at: '2026-08-06T00:00:00.000Z',
          updated_at: '2026-08-06T00:00:00.000Z',
        },
      ],
      pagination: { total: 2, page: 1, page_size: 100, pages: 1 },
    },
  })
})

it('shows extracted person assets in the selected chapter footer instead of stale analysis characters', async () => {
  const wrapper = mount(ShortDramaAgentPage, {
    global: {
      plugins: [pinia],
      components: { AppButton },
      stubs: { RouterLink: { template: '<a><slot /></a>' } },
    },
  })
  await flushPromises()

  const footer = wrapper.get('.episode-content footer')
  expect(footer.text()).toContain('宫平')
  expect(footer.text()).not.toContain('旧人物')
  expect(api.assets).toHaveBeenCalledWith(9, 1, 100, 2162)

  const editButton = wrapper.findAll('button').find(button => button.text().includes('编辑内容'))
  expect(editButton).toBeTruthy()
  await editButton?.trigger('click')
  expect(wrapper.get('button[aria-label="分镜策略"]').text()).toContain('旁白叙事')
})

it('查看者在分析任务缺失时直接预览已上传章节且不会触发模型调用', async () => {
  vi.mocked(api.novelAnalysis).mockResolvedValue({ code: 0, message: 'ok', data: null })
  const auth = useAuthStore(pinia)
  auth.$patch({
    enabled: true,
    ready: true,
    token: 'viewer-token',
    user: { id: 4, username: 'viewer', nickname: '', avatar_url: '', is_super_admin: false },
    memberships: [{ team_id: 1, team_name: '演示团队', role: 'viewer', cost_limit: 0, team_balance: 0 }],
    activeTeamId: 1,
  })

  const wrapper = mount(ShortDramaAgentPage, {
    global: {
      plugins: [pinia],
      components: { AppButton },
      stubs: { RouterLink: { template: '<a><slot /></a>' } },
    },
  })
  await flushPromises()

  expect(api.analyzeNovel).not.toHaveBeenCalled()
  expect(api.chaptersPage).toHaveBeenCalledWith(9, 1, 30)
  expect(wrapper.text()).toContain('剧本已载入')
  expect(wrapper.text()).toContain('宫平与运在雨中前行。')
  expect(wrapper.text()).not.toContain('重新分析')
  expect(wrapper.text()).not.toContain('开始分析')
})


it('reanalysis replaces the old failed run only after a new task is admitted', async () => {
  vi.mocked(api.novelAnalysis).mockResolvedValue({ code: 0, message: '', data: {
    id: 'old-run', task_type: 5, status: TaskStatusEnum.FAILED, stage: 'needs_review',
    error_message: '外部请求结果待核对，系统不会自动重试', created_at: '',
  } })
  let admit!: (result: Awaited<ReturnType<typeof api.analyzeNovel>>) => void
  vi.mocked(api.analyzeNovel).mockImplementation(() => new Promise(resolve => { admit = resolve }))
  vi.mocked(api.task).mockResolvedValue({ code: 0, message: '', data: {
    id: 'new-run', task_type: 5, status: TaskStatusEnum.COMPLETED, created_at: '',
    response_data: { book_types: ['冒险'], story_outline: '新的分析结果', key_characters: [], chapter_count: 1 },
  } })
  const wrapper = mount(ShortDramaAgentPage, { global: {
    plugins: [pinia], components: { AppButton }, stubs: { RouterLink: { template: '<a><slot /></a>' } },
  } })
  await flushPromises()
  expect(wrapper.text()).toContain('外部请求结果待核对')
  await wrapper.findAll('button').find(button => button.text() === '重新分析')!.trigger('click')
  expect(api.analyzeNovel).toHaveBeenCalledExactlyOnceWith(9)
  expect(wrapper.get('.secondary-action').attributes('disabled')).toBeDefined()
  admit({ code: 0, message: '', data: { id: 'new-run', task_type: 5, status: TaskStatusEnum.QUEUED, created_at: '' } })
  await flushPromises()
  expect(api.task).toHaveBeenCalledWith('new-run')
  expect(wrapper.text()).toContain('剧本分析完成')
  expect(wrapper.text()).toContain('冒险')
  expect(wrapper.find('.outline-card').exists()).toBe(false)
  expect(wrapper.text()).not.toContain('外部请求结果待核对')
})

it('keeps completed story analysis usable when only the cover is awaiting review', async () => {
  vi.mocked(api.novelAnalysis).mockResolvedValue({ code: 0, message: '', data: {
    id: 'cover-failed-run', task_type: 5, status: TaskStatusEnum.FAILED, stage: 'needs_review', created_at: '',
    error_message: '外部请求结果待核对，系统不会自动重试',
    response_data: { analysis_completed: true, cover_status: 'needs_review',
      cover_warning: '故事分析已完成，封面暂未生成。已保存的分析结果可以继续使用。',
      book_types: ['冒险'], story_outline: '封面失败后仍可使用的大纲',
      key_characters: [{ name: '林舟', role: '主角', description: '人物介绍', aliases: [], base_traits: '黑色短发', chapter_numbers: [1] }],
      chapter_count: 1, cover: null },
  } })
  const wrapper = mount(ShortDramaAgentPage, { global: {
    plugins: [pinia], components: { AppButton }, stubs: { RouterLink: { template: '<a><slot /></a>' } },
  } })
  await flushPromises()
  expect(wrapper.text()).toContain('剧本分析完成')
  expect(wrapper.text()).not.toContain('分析失败')
  expect(wrapper.text()).not.toContain('外部请求结果待核对')
  expect(wrapper.text()).toContain('冒险')
  expect(wrapper.text()).not.toContain('封面失败后仍可使用的大纲')
  expect(wrapper.text()).not.toContain('林舟')
  expect(wrapper.text()).not.toContain('人物小传')
  expect(wrapper.get('.creation-cover-notice').text()).toContain('封面暂未生成')
  expect(wrapper.findAll('button').some(button => button.text() === '编辑内容')).toBe(true)
  expect(wrapper.find('.analysis-progress-card').exists()).toBe(false)
  expect(api.analyzeNovel).not.toHaveBeenCalled()
})

it('sends only changed fields via patch when saving edits', async () => {
  vi.mocked(api.updateNovel).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: {
      id: 9,
      name: '修改后的名字',
    } as unknown as Novel,
  })

  const wrapper = mount(ShortDramaAgentPage, {
    global: {
      plugins: [pinia],
      components: { AppButton },
      stubs: { RouterLink: { template: '<a><slot /></a>' } },
    },
  })
  await flushPromises()

  const editButton = wrapper.findAll('button').find(button => button.text().includes('编辑内容'))
  expect(editButton).toBeTruthy()
  await editButton!.trigger('click')

  // Click "保存修改" without changes -> does not call updateNovel
  const saveButton = wrapper.findAll('button').find(button => button.text().includes('保存修改'))
  expect(saveButton).toBeTruthy()
  await saveButton!.trigger('click')
  await flushPromises()
  expect(api.updateNovel).not.toHaveBeenCalled()

  // Enter edit mode again and modify name
  await editButton!.trigger('click')
  const nameInput = wrapper.get('.analysis-title-input')
  await nameInput.setValue('修改后的名字')

  const saveButtonAfterChange = wrapper.findAll('button').find(button => button.text().includes('保存修改'))
  await saveButtonAfterChange!.trigger('click')
  await flushPromises()

  // updateNovel called with diff patch only
  expect(api.updateNovel).toHaveBeenCalledTimes(1)
  expect(api.updateNovel).toHaveBeenCalledWith(9, { name: '修改后的名字' })
})

it.each(['light', 'dark'])('shows story results while the cover is pending (%s)', async theme => {
  document.documentElement.dataset.theme = theme
  const task = {
    id: 'cover-running', task_type: 5, status: TaskStatusEnum.PROCESSING, created_at: '',
    response_data: { analysis_completed: true, cover_status: 'pending', book_types: ['冒险'],
      story_outline: '旅人回家。', key_characters: [], chapter_count: 1 },
  }
  vi.mocked(api.novelAnalysis).mockResolvedValue({ code: 0, message: '', data: task })
  vi.mocked(api.task).mockResolvedValue({ code: 0, message: '', data: task })
  const wrapper = mount(ShortDramaAgentPage, { global: {
    plugins: [pinia], components: { AppButton }, stubs: { RouterLink: { template: '<a><slot /></a>' } },
  } })
  try {
    await flushPromises()
    expect(wrapper.text()).toContain('分析已完成，封面生成中')
    expect(wrapper.find('.outline-card').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('旅人回家。')
    expect(wrapper.text()).toContain('冒险')
  } finally {
    wrapper.unmount()
    delete document.documentElement.dataset.theme
  }
})


it('opens a screenplay-only project and offers analysis on request', async () => {
  const source = (await api.novelMeta(9)).data
  vi.mocked(api.novelMeta).mockResolvedValue({code: 0, message: '', data: {...source, content_length: 0, author: undefined}})
  vi.mocked(api.chapter).mockResolvedValue({code: 0, message: '', data: {...chapter, content: '', screenplay: '1-1 雨路 外 夜\n△ 宫平与运在雨中前行。'}})
  vi.mocked(api.novelAnalysis).mockResolvedValue({code: 0, message: '', data: null})
  for (let index = 0; index < 2; index += 1) {
    const wrapper = mount(ShortDramaAgentPage, {global: {plugins: [pinia], components: {AppButton}, stubs: {RouterLink: {template: '<a><slot /></a>'}}}})
    await flushPromises()
    expect(wrapper.text()).toContain('宫平与运在雨中前行。')
    expect(wrapper.text()).toContain('剧本已载入')
    expect(wrapper.text()).not.toContain('没有可分析')
    expect(wrapper.findAll('button').some(button => button.text() === '重新分析')).toBe(true)
    expect(wrapper.findAll('button').some(button => button.text() === '生成本集剧本')).toBe(false)
    wrapper.unmount()
  }
  expect(api.analyzeNovel).not.toHaveBeenCalled()
})

it('opens the original and generates only when the user clicks, preserving both texts', async () => {
  vi.mocked(api.novelAnalysis).mockResolvedValue({code: 0, message: '', data: null})
  const saved = { ...chapter, screenplay: '# 第一集 救人\n**1-1　徐家村泥路　外　黄昏**\n出场：徐长寿\n△ 长寿牵牛停下。' }
  vi.mocked(api.chapter).mockResolvedValueOnce({code: 0, message: '', data: chapter})
    .mockResolvedValue({code: 0, message: '', data: saved})
  vi.mocked(api.generateScreenplay).mockResolvedValue({code: 0, message: '', data: {id: 'adapt', task_type: 10, status: 2, created_at: ''}})
  vi.mocked(api.task).mockResolvedValue({code: 0, message: '', data: {id: 'adapt', task_type: 10, status: 3, created_at: ''}})
  const wrapper = mount(ShortDramaAgentPage, {global: {plugins: [pinia], components: {AppButton}, stubs: {RouterLink: {template: '<a><slot /></a>'}}}})
  await flushPromises()
  expect(wrapper.get('.episode-doc-tabs [aria-pressed="true"]').text()).toBe('原文')
  expect(api.analyzeNovel).not.toHaveBeenCalled()
  expect(api.generateScreenplay).not.toHaveBeenCalled()
  await wrapper.get('.episode-doc-tools .generate-screenplay').trigger('click')
  await flushPromises()
  expect(api.generateScreenplay).toHaveBeenCalledExactlyOnceWith(chapter.id)
  expect(wrapper.get('.episode-doc-tabs [aria-pressed="true"]').text()).toBe('导演剧本')
  expect(wrapper.get('.scene-heading').text()).toBe('1-1　徐家村泥路　外　黄昏')
  await wrapper.get('.episode-doc-tabs button').trigger('click')
  expect(wrapper.text()).toContain(chapter.content)
  wrapper.unmount()
})

it('saves pacing for the selected episode and retains the draft on a save failure', async () => {
  const pacing = { preset: 'fast', max_seconds: 95 } as const
  vi.mocked(api.updateChapter).mockRejectedValueOnce(new Error('设置暂未保存'))
    .mockResolvedValueOnce({ code: 0, message: '', data: { ...chapter, episode_pacing: pacing } })
  const wrapper = mount(ShortDramaAgentPage, { attachTo: document.body, global: { plugins: [pinia],
    components: { AppButton }, stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
  try {
    await flushPromises()
    const trigger = wrapper.get<HTMLButtonElement>('.pacing-trigger')
    expect(trigger.text()).toBe('智能时长')
    const dialog = new DOMWrapper(document.body.querySelector<HTMLDialogElement>('dialog')!)
    if (!dialog.element.showModal) dialog.element.showModal = () => { dialog.element.open = true }
    await trigger.trigger('click')
    expect(dialog.element.open).toBe(true)
    await dialog.get('input[value="fast"]').setValue(true)
    const duration = dialog.get('input[type="number"]')
    await duration.setValue('0')
    expect(dialog.get<HTMLButtonElement>('[type="submit"]').element.disabled).toBe(true)
    await duration.setValue('90')
    await dialog.get('[aria-label="增加 5 秒"]').trigger('click')
    await dialog.get('form').trigger('submit')
    await flushPromises()
    expect(dialog.get('[role="alert"]').text()).toBe('设置暂未保存')
    expect(dialog.element.open).toBe(true)
    expect(trigger.text()).toBe('智能时长')
    await dialog.get('form').trigger('submit')
    await flushPromises()
    expect(api.updateChapter).toHaveBeenLastCalledWith(chapter.id, { episode_pacing: pacing })
    expect(trigger.text()).toContain('快节奏 · 最多 95 秒')
    expect(api.generateScreenplay).not.toHaveBeenCalled()
  } finally {
    wrapper.unmount()
  }
})

it.each(['light', 'dark'])('exposes the storyboard switch without edit mode and only patches its setting (%s)', async theme => {
  document.documentElement.dataset.theme = theme
  vi.mocked(api.updateNovel).mockResolvedValue({code: 0, message: 'ok', data: {id: 9, storyboard_enabled: true} as Novel})
  const wrapper = mount(ShortDramaAgentPage, {global: {plugins: [pinia], components: {AppButton}, stubs: {RouterLink: {template: '<a><slot /></a>'}}}})
  try {
    await flushPromises()
    const toggle = wrapper.get('[role="switch"][aria-label="逐镜线稿故事版"]')
    expect(toggle.attributes('aria-checked')).toBe('false')
    await toggle.trigger('click')
    await flushPromises()
    expect(api.updateNovel).toHaveBeenCalledWith(9, {storyboard_enabled: true})
    expect(toggle.attributes('aria-checked')).toBe('true')
    expect(api.analyzeNovel).not.toHaveBeenCalled()
  } finally { wrapper.unmount(); delete document.documentElement.dataset.theme }
})

it('keeps the storyboard switch off after a save failure', async () => {
  vi.mocked(api.updateNovel).mockRejectedValue(new Error('保存失败'))
  const wrapper = mount(ShortDramaAgentPage, {global: {plugins: [pinia], components: {AppButton}, stubs: {RouterLink: {template: '<a><slot /></a>'}}}})
  await flushPromises()
  await wrapper.get('[role="switch"][aria-label="逐镜线稿故事版"]').trigger('click')
  await flushPromises()
  expect(wrapper.get('[role="switch"]').attributes('aria-checked')).toBe('false')
  expect(wrapper.get('[role="switch"]').attributes('disabled')).toBeUndefined()
  wrapper.unmount()
})

it('edits the maximum shot duration without changing other project preferences', async () => {
  vi.mocked(api.updateNovel).mockResolvedValue({code: 0, message: 'ok', data: {id: 9, shot_duration_max: 12} as Novel})
  const wrapper = mount(ShortDramaAgentPage, {global: {plugins: [pinia], components: {AppButton}, stubs: {RouterLink: {template: '<a><slot /></a>'}}}})
  await flushPromises()
  expect(wrapper.get('.production-controls').text()).toContain('15s')
  await wrapper.findAll('button').find(b => b.text() === '编辑内容')!.trigger('click')
  await wrapper.get('input[aria-label="单分镜最长时长"]').setValue(12)
  await wrapper.findAll('button').find(b => b.text().includes('保存修改'))!.trigger('click')
  await flushPromises()
  expect(api.updateNovel).toHaveBeenCalledWith(9, {shot_duration_max: 12})
  wrapper.unmount()
})


it.each([true, false])('previews the duration during a drag and saves only on release (success=%s)', async success => {
  const save = vi.mocked(api.updateNovel)
  if (success) save.mockResolvedValue({code: 0, message: 'ok', data: {id: 9, shot_duration_max: 22} as Novel})
  else save.mockRejectedValue(new Error('保存失败'))
  const wrapper = mount(ShortDramaAgentPage, {global: {plugins: [pinia], components: {AppButton}, stubs: {RouterLink: {template: '<a><slot /></a>'}}}})
  try {
    await flushPromises()
    const range = wrapper.get<HTMLInputElement>('input[type="range"][aria-label="单分镜最长时长"]')
    range.element.value = '22'
    await range.trigger('input')
    expect(wrapper.get('output.duration-value').text()).toBe('22s')
    expect(save).not.toHaveBeenCalled()
    await range.trigger('change')
    await flushPromises()
    expect(save).toHaveBeenCalledExactlyOnceWith(9, {shot_duration_max: 22})
    expect(range.element.value).toBe(success ? '22' : '15')
    expect(range.element.disabled).toBe(false)
  } finally { wrapper.unmount() }
})

it('cancels and saves the title-row project format and custom visual style', async () => {
  vi.mocked(api.updateNovel).mockImplementation(async (_id, patch) => ({code: 0, message: '', data: {...patch, id: 9, name: chapter.name} as Novel}))
  const wrapper = mount(ShortDramaAgentPage, {global: {plugins: [pinia], components: {AppButton}, stubs: {RouterLink: {template: '<a><slot /></a>'}}}})
  const action = (text: string) => wrapper.findAll('button').find(b => b.text() === text)!.trigger('click')
  async function choose(label: string, value: string) {
    await wrapper.get(`button[aria-label="${label}"]`).trigger('click')
    const option = [...document.querySelectorAll<HTMLElement>('[role=option]')].find(el => el.textContent?.trim() === value)
    expect(option).toBeDefined()
    option!.click()
    await flushPromises()
  }
  try {
    await flushPromises()
    await action('编辑内容')
    await choose('画面比例', '16:9')
    await action('取消')
    expect(api.updateNovel).not.toHaveBeenCalled()
    await action('编辑内容')
    await choose('画面比例', '16:9')
    await choose('分辨率', '1080p')
    await choose('视觉风格', '自定义风格')
    await wrapper.get('textarea[aria-label="自定义风格"]').setValue('水墨淡彩')
    await action('保存修改')
    await flushPromises()
    expect(api.updateNovel).toHaveBeenCalledExactlyOnceWith(9, {aspect_ratio: '16:9', resolution: '1080p', style_key: null, custom_style_prompt: '水墨淡彩'})
    expect(wrapper.get('.episode-project-meta').text()).toContain('1080p')
    expect(wrapper.get('[title="水墨淡彩"]').text()).toContain('自定义风格')
  } finally { wrapper.unmount() }
})

it('offers regeneration on the original tab and keeps the existing screenplay when cancelled', async () => {
  const {appConfirmState, resolveAppConfirm} = await import('@/shared/confirmDialog')
  vi.mocked(api.chapter).mockResolvedValue({code: 0, message:'', data:{...chapter, screenplay:'已确认导演稿'}})
  const wrapper = mount(ShortDramaAgentPage, {global:{plugins:[pinia],components:{AppButton},stubs:{RouterLink:{template:'<a><slot /></a>'}}}})
  try {
    await flushPromises()
    await wrapper.get('.episode-doc-tabs button').trigger('click')
    const button = wrapper.get('.episode-doc-tools .generate-screenplay')
    expect(button.text()).toBe('重新生成本集剧本')
    await button.trigger('click')
    expect(appConfirmState.open).toBe(true)
    resolveAppConfirm(false)
    await flushPromises()
    expect(api.generateScreenplay).not.toHaveBeenCalled()
  } finally { wrapper.unmount() }
})


it('offers an episode and the creative assistant in a blank workspace without starting generation', async () => {
  const source = (await api.novelMeta(9)).data
  vi.mocked(api.novelMeta).mockResolvedValue({code: 0, message: '', data: {...source, total_chapters: 0, content_length: 0}})
  vi.mocked(api.novelAnalysis).mockResolvedValue({code: 0, message: '', data: null})
  vi.mocked(api.chaptersPage).mockResolvedValue({code: 0, message: '', data: {items: [], pagination: {total: 0, page: 1, page_size: 30, pages: 0}}})
  vi.mocked(api.chapter).mockRejectedValueOnce(new Error('章节不存在'))
  const wrapper = mount(ShortDramaAgentPage, {global: {
    plugins: [pinia], components: {AppButton},
    stubs: {RouterLink: {template: '<a><slot /></a>'}, CreationAgentPanel: true},
  }})
  await flushPromises()
  expect(wrapper.findAll('button').some(button => button.text() === '新增一集')).toBe(true)
  const assistant = wrapper.findAll('button').find(button => button.text() === '与助手开始创作')!
  expect(assistant).toBeTruthy()
  await assistant.trigger('click')
  expect(useCreationAgentWorkspace().isOpen).toBe(true)
  expect(useCreationAgentWorkspace().projectId).toBe(9)
  expect(api.analyzeNovel).not.toHaveBeenCalled()
  expect(api.generateScreenplay).not.toHaveBeenCalled()
  wrapper.unmount()
})


it.each(['light', 'dark'])('generates a cover separately and updates the action once saved (%s)', async theme => {
  document.documentElement.dataset.appTheme = theme
  vi.mocked(api.generateNovelCover).mockResolvedValueOnce({code: 0, message: '', data: {
    id: 'cover-run', task_type: 5, status: TaskStatusEnum.QUEUED, created_at: '',
  }})
  vi.mocked(api.task).mockResolvedValueOnce({code: 0, message: '', data: {
    id: 'cover-run', task_type: 5, status: TaskStatusEnum.COMPLETED, created_at: '', response_data: {cover_status: 'ready'},
  }})
  const initial = await api.novelMeta(9)
  vi.mocked(api.novelMeta).mockClear()
  vi.mocked(api.novelMeta).mockResolvedValueOnce(initial)
    .mockResolvedValueOnce({...initial, data: {...initial.data, cover: '/media/new-cover.png'}})
  const wrapper = mount(ShortDramaAgentPage, {global: {
    plugins: [pinia], components: {AppButton}, stubs: {RouterLink: {template: '<a><slot /></a>'}},
  }})
  try {
    await flushPromises()
    const action = wrapper.get('.cover-generation-actions')
    expect(action.findAll('button').map(button => button.text())).toEqual(['选择封面模型', '生成封面'])
    expect(action.findAll('button')[1]!.attributes('disabled')).toBeDefined()
    wrapper.getComponent(ImageModelSelect).vm.$emit('update:modelValue', '23')
    await flushPromises()
    await action.findAll('button')[1]!.trigger('click')
    await flushPromises()
    expect(api.generateNovelCover).toHaveBeenCalledExactlyOnceWith(9, 23)
    expect(api.analyzeNovel).not.toHaveBeenCalled()
    expect(action.findAll('button')[1]!.text()).toBe('重新生成封面')
  } finally {
    wrapper.unmount()
    delete document.documentElement.dataset.appTheme
  }
})
