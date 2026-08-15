import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ShortDramaWorkspaceShell from './ShortDramaWorkspaceShell.vue'

const routerPush = vi.fn()

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: { chapter: '12' } }),
  useRouter: () => ({ push: routerPush }),
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
  it('keeps the video phase locked until the current episode has a playable result', async () => {
    routerPush.mockClear()
    const wrapper = mount(ShortDramaWorkspaceShell, { props: baseProps })
    const videoButton = wrapper.findAll('.short-drama-phase-nav button').find(button => button.text().includes('视频'))
    expect(videoButton?.attributes('disabled')).toBeDefined()

    await wrapper.setProps({ videoEnabled: true })
    const enabledVideoButton = wrapper.findAll('.short-drama-phase-nav button').find(button => button.text().includes('视频'))
    await enabledVideoButton?.trigger('click')
    expect(routerPush).toHaveBeenCalledWith({
      path: '/create/short-drama/video/1',
      query: { chapter: '12' },
    })
  })

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

  it('marks immersive workspaces so canvas controls can layer above the transparent shell header', () => {
    const wrapper = mount(ShortDramaWorkspaceShell, {
      props: { ...baseProps, immersive: true },
      slots: { default: '<div class="workbench-toolbar">画布工具栏</div>' },
    })

    expect(wrapper.classes()).toContain('is-immersive')
    expect(wrapper.find('.short-drama-project-identity').exists()).toBe(true)
    expect(wrapper.get('.workbench-toolbar').text()).toBe('画布工具栏')
  })
})
