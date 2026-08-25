import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import AppButton from '@/components/AppButton.vue'
import { AssetTypeEnum, TaskStatusEnum } from '@/types'
import ShortDramaAgentPage from './ShortDramaAgentPage.vue'

const push = vi.fn()
const replace = vi.fn()

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { projectId: '9' }, query: { chapter: '2162' } }),
  useRouter: () => ({ push, replace, back: vi.fn() }),
}))

vi.mock('@/api', () => ({
  api: {
    configs: vi.fn(),
    novel: vi.fn(),
    novelMeta: vi.fn(),
    novelAnalysis: vi.fn(),
    chapters: vi.fn(),
    chaptersPage: vi.fn(),
    chapter: vi.fn(),
    assets: vi.fn(),
    storyboardStrategies: vi.fn(),
  },
}))

const chapter = {
  id: 2162,
  novel_id: 9,
  number: 1,
  name: '厄运之手',
  content: '宫平与运在雨中前行。',
  created_at: '2026-08-06T00:00:00.000Z',
  updated_at: '2026-08-06T00:00:00.000Z',
}

beforeEach(() => {
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
      content_length: 0,
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
