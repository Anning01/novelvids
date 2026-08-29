import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api'
import AppButton from '@/components/AppButton.vue'
import ShortDramaPage from './ShortDramaPage.vue'

const push = vi.fn()

vi.mock('vue-router', () => ({
  useRouter: () => ({ push }),
}))

vi.mock('@/api', () => ({
  api: {
    visualStyles: vi.fn(),
    storyboardStrategies: vi.fn(),
    createNovel: vi.fn(),
  },
}))

beforeEach(() => {
  push.mockReset()
  sessionStorage.clear()
  vi.mocked(api.visualStyles).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: [{ key: 'realistic-general', label: '写实通用' }],
  })
  vi.mocked(api.storyboardStrategies).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: [
      { key: 'cinematic', name: '电影感叙事', description: '原电影感规则', is_default: true },
      { key: 'narration', name: '旁白叙事', description: '旁白规则', is_default: false },
    ],
  })
  vi.mocked(api.createNovel).mockResolvedValue({
    code: 0,
    message: 'ok',
    data: {
      id: 19,
      name: '新项目',
      storyboard_strategy: 'narration',
      storyboard_setting: '旁白规则',
      created_at: '',
      updated_at: '',
    },
  })
})

it('selects a backend strategy on project creation and persists it', async () => {
  const wrapper = mount(ShortDramaPage, {
    global: { components: { AppButton } },
  })
  await flushPromises()

  const strategyTrigger = wrapper.get('button[aria-label="分镜策略"]')
  expect(strategyTrigger.text()).toContain('电影感叙事')
  await strategyTrigger.trigger('click')
  await flushPromises()
  const narrationOption = document.body.querySelectorAll<HTMLElement>('[role="option"]')
  const target = [...narrationOption].find(option => option.textContent?.includes('旁白叙事'))
  expect(target).toBeTruthy()
  target?.click()
  await flushPromises()

  const manualButton = wrapper.findAll('button').find(button => button.text().includes('人工模式'))
  expect(manualButton).toBeTruthy()
  await manualButton?.trigger('click')
  await wrapper.get('form').trigger('submit')
  await flushPromises()

  expect(api.createNovel).toHaveBeenCalledWith(expect.objectContaining({
    storyboard_strategy: 'narration',
    storyboard_setting: '旁白规则',
    description: '人工模式',
    aspect_ratio: '9:16',
    resolution: '720p',
    style_key: 'realistic-general',
    custom_style_prompt: null,
  }))
})
