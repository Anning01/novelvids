import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ShortDramaWorkspaceShell from './ShortDramaWorkspaceShell.vue'
import { api } from '@/api'

vi.mock('@/api', async importOriginal => {
  const actual = await importOriginal<typeof import('@/api')>()
  return { ...actual, api: { ...actual.api, visualStyles: vi.fn().mockResolvedValue({ data: [{ key: 'realistic-general', label: '写实通用' }] }) } }
})

beforeEach(() => setActivePinia(createPinia()))
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
  it('displays the backend visual-style label and preserves custom names when lookup fails', async () => {
    const wrapper = mount(ShortDramaWorkspaceShell, { props: { ...baseProps, styleName: 'realistic-general' } })
    await flushPromises()
    expect(wrapper.get('.short-drama-project-meta').text()).toContain('写实通用')
    expect(wrapper.get('.short-drama-project-meta').text()).not.toContain('realistic-general')
    await wrapper.setProps({ styleName: '低饱和胶片质感' })
    expect(wrapper.get('.short-drama-project-meta').text()).toContain('低饱和胶片质感')
    wrapper.unmount()
    vi.mocked(api.visualStyles).mockRejectedValueOnce(new Error('offline'))
    const reopened = mount(ShortDramaWorkspaceShell, { props: baseProps })
    await flushPromises()
    expect(reopened.get('.short-drama-project-meta').text()).toContain('写实')
    reopened.unmount()
  })
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

  it('loads one shared assistant panel and restores focus when it closes', async () => {
    const wrapper = mount(ShortDramaWorkspaceShell, {
      props: baseProps,
      attachTo: document.body,
      slots: { default: '<textarea aria-label="未保存草稿">保留草稿</textarea>' },
      global: { stubs: { CreationAgentPanel: { emits: ['close'], template: '<aside aria-label="创作助手"><button @click="$emit(\'close\')">关闭创作助手</button></aside>' } } },
    })
    const trigger = wrapper.get('button[aria-expanded="false"]')
    const draft = wrapper.get('textarea').element
    await trigger.trigger('click')
    expect(wrapper.classes()).toContain('has-assistant')
    const content = wrapper.get('.short-drama-workspace-content')
    expect(content.get('.short-drama-workspace-body').element.parentElement).toBe(content.element)
    expect(content.get('aside').element.parentElement).toBe(content.element)
    await wrapper.get('aside[aria-label="创作助手"] button').trigger('click')
    expect(wrapper.classes()).not.toContain('has-assistant')
    expect(wrapper.get('textarea').element).toBe(draft)
    expect((draft as HTMLTextAreaElement).value).toBe('保留草稿')
    expect(document.activeElement).toBe(trigger.element)
    expect(wrapper.find('aside[aria-label="创作助手"]').exists()).toBe(false)
    wrapper.unmount()
  })
})

it('keeps an open assistant across production page remounts with explicit target context', async () => {
  const pinia = createPinia()
  const settings = { props: baseProps, global: { plugins: [pinia], stubs: {
    CreationAgentPanel: { template: '<aside aria-label="创作助手" />' },
  } } }
  const first = mount(ShortDramaWorkspaceShell, settings)
  first.vm.editWithAssistant([{ target: { kind: 'asset', id: 42 }, label: '林夏' }])
  await first.vm.$nextTick()
  expect(first.find('[aria-label="创作助手"]').exists()).toBe(true)
  first.unmount()
  const second = mount(ShortDramaWorkspaceShell, { ...settings, props: { ...baseProps, activePhase: 'storyboard' } })
  expect(second.classes()).toContain('has-assistant')
  expect(second.find('[aria-label="创作助手"]').exists()).toBe(true)
  second.unmount()
})
