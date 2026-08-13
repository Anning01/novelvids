import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ShortDramaWorkspaceShell from './ShortDramaWorkspaceShell.vue'

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: { chapter: '12' } }),
  useRouter: () => ({ push: vi.fn() }),
}))

const chapter = { id: 12, novel_id: 1, number: 2, name: '追踪', created_at: '', updated_at: '' }
const baseProps = {
  projectId: 1,
  projectName: '项目',
  aspectRatio: '16:9',
  resolution: '720p',
  styleName: '写实',
  activePhase: 'settings' as const,
  chapters: [chapter],
  activeChapterId: 12,
}

describe('ShortDramaWorkspaceShell', () => {
  it('shares the fixed header and episode rail for production phases', () => {
    const wrapper = mount(ShortDramaWorkspaceShell, { props: baseProps })
    wrapper.get('.short-drama-workspace-header')
    wrapper.get('[aria-label="集数导航"]')
    expect(wrapper.get('button[aria-current="step"]').text()).toContain('设定')
  })

  it('hides the episode rail on the script phase', () => {
    const wrapper = mount(ShortDramaWorkspaceShell, {
      props: { ...baseProps, activePhase: 'script' },
    })
    expect(wrapper.find('[aria-label="集数导航"]').exists()).toBe(false)
  })
})
