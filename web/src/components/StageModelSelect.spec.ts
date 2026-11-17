import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import StageModelSelect from './StageModelSelect.vue'
import AppSelect from './AppSelect.vue'
import { skillsApi } from '@/features/creation-agent/skillsApi'

vi.mock('@/features/creation-agent/skillsApi', () => ({ skillsApi: { models: vi.fn() } }))
beforeEach(() => { vi.resetAllMocks(); sessionStorage.clear() })

it.each(['assets', 'storyboard'] as const)('loads strict models and discards a retired selection for %s', async stage => {
  sessionStorage.setItem(`novelvids:model:7:${stage}`, '3')
  vi.mocked(skillsApi.models).mockResolvedValue({ code: 0, message: '', data: [{ id: 8, name: '严格模型', model: 'strict' }] })
  const wrapper = mount(StageModelSelect, { props: { projectId: 7, stage, label: '选择模型', disabled: false, modelValue: '3' } })
  await flushPromises()
  expect(skillsApi.models).toHaveBeenCalledOnce()
  expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([''])
  expect(wrapper.getComponent(AppSelect).props('options')).toContainEqual({ value: '8', label: '严格模型' })
  expect(wrapper.getComponent(AppSelect).props('options')).not.toContainEqual(expect.objectContaining({ value: '3' }))
})

it('shows the strict model empty state and supports retry after a load error', async () => {
  vi.mocked(skillsApi.models).mockRejectedValueOnce(new Error('读取失败'))
  const wrapper = mount(StageModelSelect, { props: { projectId: 7, stage: 'assets', label: '选择模型', disabled: false, modelValue: '' } })
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toBe('读取失败')
  vi.mocked(skillsApi.models).mockResolvedValue({ code: 0, message: '', data: [] })
  await wrapper.findAll('button').find(button => button.text() === '重试')!.trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('暂无 JSON Schema 输出模型')
  expect(wrapper.find('[role="alert"]').exists()).toBe(false)
})
