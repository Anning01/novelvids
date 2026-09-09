import { createPinia } from 'pinia'
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CreationAgentPanel from './CreationAgentPanel.vue'
import { agentApi } from './api'
import { api } from '@/api'
import { useCreationAgentStore } from './store'

const { push, scrollToBottom } = vi.hoisted(() => ({ push: vi.fn(), scrollToBottom: vi.fn() }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push }) }))
vi.mock('./api', () => ({ agentApi: { promptStatus: vi.fn(), capabilities: vi.fn(), conversations: vi.fn(), history: vi.fn() }, runSubscription: vi.fn() }))
vi.mock('@/api', () => ({ api: { assets: vi.fn(), scenes: vi.fn() }, getAuthToken: () => null, getActiveTeamId: () => null }))
vi.mock('vue-element-plus-x', () => ({
  BubbleList: defineComponent({ props: ['list'], setup(_, { expose }) { expose({ scrollToBottom }) }, template: '<div><div v-for="item in list" :key="item.id"><slot name="content" :item="item"/><slot name="footer" :item="item"/></div></div>' }),
}))

vi.mock('./AgentComposer.vue', () => ({ default: defineComponent({
  setup(_, { expose }) { expose({ focus: vi.fn() }) },
  name: 'AgentComposer', props: ['modelValue', 'modelId', 'models', 'disabled', 'busy'], emits: ['submit', 'update:modelValue', 'update:modelId'],
  template: `<div><button data-testid="sender" :disabled="disabled || busy" @click="$emit('submit', modelValue || '灯光柔和一点')">发送</button><textarea aria-label="创作要求" :value="modelValue" @input="$emit('update:modelValue', $event.target.value)"/><select aria-label="助手模型" :value="modelId" @change="$emit('update:modelId', $event.target.value)"><option v-for="model in models" :key="model.id" :value="String(model.id)">{{ model.name }}</option></select></div>`,
}) }))

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(agentApi.promptStatus).mockResolvedValue({ code: 0, message: "", data: [] })
  vi.mocked(agentApi.capabilities).mockResolvedValue({ code: 0, message: '', data: { enabled: true, can_write: true, max_targets: 2, models: [{ id: 1, name: '助手模型', model: 'model' }] } })
  vi.mocked(agentApi.conversations).mockResolvedValue({ code: 0, message: '', data: [] })
  vi.mocked(api.assets).mockResolvedValue({ code: 0, message: '', data: { items: [], pagination: { page: 1, pages: 1, total: 0, page_size: 50 } } })
  vi.mocked(api.scenes).mockResolvedValue({ code: 0, message: '', data: { items: [{ id: 9, chapter_id: 3, sequence: 1, description: '夜晚车站', created_at: '', updated_at: '' }], pagination: { page: 1, pages: 1, total: 1, page_size: 100 } } })
})

describe('creation assistant panel', () => {
  it('shows conversation history and new conversation above messages, with model selection below the sender', async () => {
    vi.mocked(agentApi.conversations).mockResolvedValue({ code: 0, message: '', data: [
      { id: 8, novel_id: 7, active_task_id: null, created_at: '2026-09-05T08:00:00Z', updated_at: '2026-09-05T09:30:00Z' },
      { id: 3, novel_id: 7, active_task_id: null, created_at: '2026-09-04T08:00:00Z', updated_at: '2026-09-04T09:30:00Z' },
    ] })
    const pinia = createPinia()
    const wrapper = mount(CreationAgentPanel, { props: { projectId: 7, chapterId: 3 }, global: { plugins: [pinia] } })
    await flushPromises()

    expect(wrapper.get('[aria-label="对话记录"]').text()).toContain('对话 8')
    expect(wrapper.findAll('button').some(button => button.text().includes('新会话'))).toBe(true)
    const senderElement = wrapper.get('[data-testid="sender"]').element
    const modelElement = wrapper.get('[aria-label="助手模型"]').element
    expect(senderElement.compareDocumentPosition(modelElement) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

    const store = useCreationAgentStore(pinia)
    const createConversation = vi.spyOn(store, 'newConversation').mockResolvedValue(undefined)
    await wrapper.findAll('button').find(button => button.text().includes('新会话'))!.trigger('click')
    expect(createConversation).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('preserves manual scope when the page refreshes the same default target', async () => {
    const pinia = createPinia()
    const wrapper = mount(CreationAgentPanel, { props: { projectId: 7, chapterId: 3, selectedTargets: [{ kind: 'scene', id: 9 }] }, global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text().includes('修改范围'))!.trigger('click')
    await wrapper.get('input[value="scene:9"]').setValue(false)
    await wrapper.setProps({ selectedTargets: [{ kind: 'scene', id: 9 }] })
    expect(wrapper.text()).toContain('选择需要修改的对象')
    expect((wrapper.get('input[value="scene:9"]').element as HTMLInputElement).checked).toBe(false)
    await wrapper.get('input[value="scene:9"]').setValue(true)
    await wrapper.setProps({ selectedTargets: [{ kind: 'scene', id: 10 }] })
    const send = vi.spyOn(useCreationAgentStore(pinia), 'send').mockResolvedValue(true)
    await wrapper.get('[data-testid="sender"]').trigger('click')
    expect(send).toHaveBeenCalledWith(expect.objectContaining({ targets: [{ kind: 'scene', id: 9 }] }))
    wrapper.unmount()
  })

  it('selects an existing variant independently from its parent asset', async () => {
    vi.mocked(api.assets).mockResolvedValue({ code: 0, message: '', data: {
      items: [{ id: 8, novel_id: 7, asset_type: 1, canonical_name: '女主', created_at: '', updated_at: '',
        variants: [{ id: 701, asset_id: 8, name: '雨夜风衣', images: [], created_at: '', updated_at: '' }] }],
      pagination: { page: 1, pages: 1, total: 1, page_size: 50 },
    } })
    const pinia = createPinia()
    const wrapper = mount(CreationAgentPanel, { props: { projectId: 7, chapterId: 3 }, global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '选择需要修改的对象')!.trigger('click')
    expect(wrapper.text()).toContain('女主 · 雨夜风衣')
    await wrapper.get('input[value="variant:701"]').setValue(true)
    const send = vi.spyOn(useCreationAgentStore(pinia), 'send').mockResolvedValue(true)
    await wrapper.get('[data-testid="sender"]').trigger('click')
    expect(send).toHaveBeenCalledWith(expect.objectContaining({ targets: [{ kind: 'variant', id: 701 }] }))
    wrapper.unmount()
  })

  it('uses selected scene context and does not ask users to edit raw prompts', async () => {
    const pinia = createPinia()
    const wrapper = mount(CreationAgentPanel, { props: { projectId: 7, chapterId: 3, selectedTargets: [{ kind: 'scene', id: 9 }] }, global: { plugins: [pinia] } })
    await flushPromises()
    expect(wrapper.text()).toContain('已选 1 个对象')
    const store = useCreationAgentStore(pinia)
    const send = vi.spyOn(store, 'send').mockResolvedValue(true)
    await wrapper.get('[data-testid="sender"]').trigger('click')
    expect(send).toHaveBeenCalledWith({ message: '灯光柔和一点', chapter_id: 3, model_config_id: 1, targets: [{ kind: 'scene', id: 9 }] })
  })

  it('disables sending when the server feature flag is off', async () => {
    vi.mocked(agentApi.capabilities).mockResolvedValue({ code: 0, message: '', data: { enabled: false, can_write: true, max_targets: 2, models: [] } })
    const wrapper = mount(CreationAgentPanel, { props: { projectId: 7, chapterId: 3 }, global: { plugins: [createPinia()] } })
    await flushPromises()
    expect(wrapper.text()).toContain('尚未启用')
    expect(wrapper.find('[data-testid="sender"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="助手连接状态"]').exists()).toBe(true)
    await wrapper.get('[aria-label="关闭创作助手"]').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('passes the exact change id from the reusable card to undo', async () => {
    const pinia = createPinia()
    const wrapper = mount(CreationAgentPanel, { props: { projectId: 7, chapterId: 3 }, global: { plugins: [pinia] } })
    await flushPromises()
    const store = useCreationAgentStore(pinia)
    store.messages = [{ id: 1, role: 'assistant', content: '已修改', task_id: 'task', status: 3, usage: {}, created_at: '',
      changes: [{ id: 13, task_id: 'task', changes: [], created_at: '', reverted_at: null }] }]
    const undo = vi.spyOn(store, 'undo').mockResolvedValue(undefined)
    await flushPromises()
    const button = wrapper.findAll('button').find(item => item.text().includes('撤销这次修改'))!
    await button.trigger('click')
    expect(undo).toHaveBeenCalledWith(13)
  })
})

it('locates a variant through its parent asset even when the catalog does not contain it', async () => {
  const pinia = createPinia()
  const wrapper = mount(CreationAgentPanel, { props: { projectId: 7, chapterId: 3 }, global: { plugins: [pinia] } })
  await flushPromises()
  const store = useCreationAgentStore(pinia)
  store.messages = [{ id: 1, role: 'assistant', content: '已修改', task_id: 'task', status: 3, usage: {}, created_at: '',
    changes: [{ id: 13, task_id: 'task', created_at: '', reverted_at: null,
      changes: [{ kind: 'variant', target_id: 31, asset_id: 8, before: {}, after: { base_traits: '雨衣' }, after_version: 'v1' }] }] }]
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === '查看差异')!.trigger('click')
  await wrapper.findAll('button').find(button => button.text().includes('查看图片设定'))!.trigger('click')
  expect(push).toHaveBeenCalledWith({ path: '/create/short-drama/manual/7', query: { chapter: 3, asset: 8, variant: 31 } })
  wrapper.unmount()
})

it('keeps the dock nonmodal on narrow screens and supports Escape to close', async () => {
  vi.stubGlobal('innerWidth', 390)
  const wrapper = mount(CreationAgentPanel, { props: { projectId: 7, chapterId: 3 }, global: { plugins: [createPinia()] } })
  try {
    await flushPromises()
    expect(wrapper.attributes('aria-modal')).toBeUndefined()
    expect(wrapper.attributes('role')).not.toBe('dialog')
    await wrapper.trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('close')).toHaveLength(1)
  } finally {
    wrapper.unmount()
    vi.unstubAllGlobals()
  }
})

it('shows scoped pending rules without sending a request or changing selection', async () => {
  vi.mocked(agentApi.promptStatus).mockResolvedValue({ code: 0, message: '', data: [
    { kind: 'scene', id: 9, pending_constraints: [{ id: 4, content: '当前场景使用柔和暖光' }] },
  ] })
  const pinia = createPinia()
  const wrapper = mount(CreationAgentPanel, { props: { projectId: 7, chapterId: 3 }, global: { plugins: [pinia] } })
  await flushPromises()
  const send = vi.spyOn(useCreationAgentStore(pinia), 'send')
  expect(wrapper.text()).toContain('有 1 个需核对新约束')
  expect(wrapper.text()).toContain('历史提示词尚未自动更新')
  await wrapper.findAll('button').find(button => button.text() === '查看对象')!.trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('待核对约束')
  expect(wrapper.text()).toContain('当前场景使用柔和暖光')
  expect(wrapper.get<HTMLInputElement>('input[type="checkbox"]').element.checked).toBe(false)
  expect(send).not.toHaveBeenCalled()
  vi.mocked(agentApi.promptStatus).mockResolvedValue({ code: 0, message: '', data: [{ kind: 'scene', id: 9, pending_constraints: [] }] })
  useCreationAgentStore(pinia).changesRevision += 1
  await flushPromises()
  expect(wrapper.text()).not.toContain('待核对约束')
  wrapper.unmount()
})

it('does not show status returned for a previous chapter after switching chapters', async () => {
  let resolveOld: (value: Awaited<ReturnType<typeof agentApi.promptStatus>>) => void = () => {}
  vi.mocked(agentApi.promptStatus).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
  const wrapper = mount(CreationAgentPanel, { props: { projectId: 7, chapterId: 3 }, global: { plugins: [createPinia()] } })
  await flushPromises()
  await wrapper.setProps({ chapterId: 4 })
  await flushPromises()
  resolveOld({ code: 0, message: '', data: [{ kind: 'scene', id: 9, pending_constraints: [{ id: 1, content: '前章旧状态' }] }] })
  await flushPromises()
  expect(wrapper.text()).not.toContain('需核对新约束')
  wrapper.unmount()
})

it('preserves draft and model choice after closing and reopening the assistant', async () => {
  vi.mocked(agentApi.capabilities).mockResolvedValue({ code: 0, message: '', data: {
    enabled: true, can_write: true, max_targets: 2, models: [{ id: 1, name: '默认模型', model: 'first' }, { id: 2, name: '所选模型', model: 'second' }],
  } })
  const pinia = createPinia()
  const settings = { props: { projectId: 7, chapterId: 3 }, global: { plugins: [pinia] } }
  const first = mount(CreationAgentPanel, settings)
  await flushPromises()
  await first.get('[aria-label="创作要求"]').setValue('先保留草稿，不要发送')
  await first.get('[aria-label="助手模型"]').setValue('2')
  first.unmount()
  const reopened = mount(CreationAgentPanel, settings)
  await flushPromises()
  expect(reopened.get<HTMLTextAreaElement>('[aria-label="创作要求"]').element.value).toBe('先保留草稿，不要发送')
  expect(reopened.get<HTMLSelectElement>('[aria-label="助手模型"]').element.value).toBe('2')
  await reopened.setProps({ chapterId: 4 })
  await flushPromises()
  expect(reopened.get<HTMLTextAreaElement>('[aria-label="创作要求"]').element.value).toBe('先保留草稿，不要发送')
  expect(reopened.get<HTMLSelectElement>('[aria-label="助手模型"]').element.value).toBe('2')
  reopened.unmount()
})

it('sends an explicit page selection even beyond the first catalog page', async () => {
  const { useCreationAgentWorkspace } = await import('./workspace')
  const pinia = createPinia()
  const workspace = useCreationAgentWorkspace(pinia)
  workspace.editTargets(7, 3, [{ target: { kind: 'asset', id: 999 }, label: '远页角色' }])
  const wrapper = mount(CreationAgentPanel, { props: { projectId: 7, chapterId: 3 }, global: { plugins: [pinia] } })
  await flushPromises()
  expect(wrapper.get('[aria-label="已选修改对象"]').text()).toContain('远页角色')
  expect(agentApi.promptStatus).toHaveBeenLastCalledWith(7, 3, expect.arrayContaining([{ kind: 'asset', id: 999 }]))
  const send = vi.spyOn(useCreationAgentStore(pinia), 'send').mockResolvedValue(true)
  await wrapper.get('[data-testid="sender"]').trigger('click')
  expect(send).toHaveBeenCalledWith(expect.objectContaining({ targets: [{ kind: 'asset', id: 999 }] }))
  workspace.editTargets(7, 3, [{ target: { kind: 'scene', id: 1000 }, label: '另一个分镜' }])
  await flushPromises()
  expect(agentApi.promptStatus).toHaveBeenLastCalledWith(7, 3, expect.arrayContaining([{ kind: 'scene', id: 1000 }]))
  await wrapper.get('[data-testid="sender"]').trigger('click')
  expect(send).toHaveBeenLastCalledWith(expect.objectContaining({ targets: [{ kind: 'scene', id: 1000 }] }))
  wrapper.unmount()
})

it('filters the object picker without losing selected targets', async () => {
  const wrapper = mount(CreationAgentPanel, { props: { projectId: 7, chapterId: 3, selectedTargets: [{ kind: 'scene', id: 9 }] }, global: { plugins: [createPinia()] } })
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text().includes('修改范围'))!.trigger('click')
  await wrapper.get('[aria-label="搜索修改对象"]').setValue('不存在的角色')
  expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false)
  expect(wrapper.text()).toContain('已选 1 个对象')
  await wrapper.get('[aria-label="搜索修改对象"]').setValue('车站')
  expect(wrapper.get<HTMLInputElement>('input[type="checkbox"]').element.checked).toBe(true)
  wrapper.unmount()
})

it('keeps failed rounds visible and restores the request for editing without resubmission', async () => {
  const pinia = createPinia()
  const wrapper = mount(CreationAgentPanel, { props: { projectId: 7, chapterId: 3 }, global: { plugins: [pinia] } })
  await flushPromises()
  const store = useCreationAgentStore(pinia)
  store.messages = [
    { id: 1, role: 'user', content: '保留人物，调柔灯光', task_id: 'failed', status: 4, changes: [], usage: {}, created_at: '' },
    { id: 2, role: 'assistant', content: '', task_id: 'failed', status: 4, changes: [], usage: {}, created_at: '' },
  ]
  store.currentRun = { task_id: 'failed', conversation_id: 1, status: 4, content: '', error_message: '模型输出达到上限', changes: [], usage: {}, event_count: 1 }
  store.error = '模型输出达到上限'
  await flushPromises()
  const send = vi.spyOn(store, 'send')
  expect(wrapper.text()).toContain('本轮未完成，尚未保存修改')
  await wrapper.findAll('button').find(button => button.text() === '编辑后重试')!.trigger('click')
  expect(wrapper.get<HTMLTextAreaElement>('[aria-label="创作要求"]').element.value).toBe('保留人物，调柔灯光')
  expect(send).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('opens restored history at the latest message', async () => {
  const pinia = createPinia()
  const wrapper = mount(CreationAgentPanel, { props: { projectId: 7, chapterId: 3 }, global: { plugins: [pinia] } })
  await flushPromises()
  const store = useCreationAgentStore(pinia)
  store.loading = true
  await flushPromises()
  store.messages = [{ id: 1, role: 'assistant', content: '最新修改已完成', task_id: 'done', status: 3, changes: [], usage: {}, created_at: '' }]
  store.loading = false
  await flushPromises()
  expect(scrollToBottom).toHaveBeenCalledWith(false)
  wrapper.unmount()
})
