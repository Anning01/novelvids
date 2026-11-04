import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import CatalogVoiceUpload from './CatalogVoiceUpload.vue'
import { catalogApi } from './catalog'
import AudioRangeSlider from '@/components/AudioRangeSlider.vue'
import AppButton from '@/components/AppButton.vue'

vi.mock('./catalog', () => ({ catalogApi: { uploadVoice: vi.fn() } }))

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('URL', { ...URL, createObjectURL: vi.fn(() => 'blob:voice'), revokeObjectURL: vi.fn() })
})

function render() {
  return mount(CatalogVoiceUpload, { props: { folderId: 7 }, global: { plugins: [createPinia()], components: { AppButton } } })
}

async function pickFile(wrapper: ReturnType<typeof render>, file: File) {
  const input = wrapper.get('input[type="file"]')
  Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })
  await input.trigger('change')
}

it('organizes the form as labelled fields with an audio drop zone instead of the native control', () => {
  const wrapper = render()
  const labels = wrapper.findAll('.catalog-upload__label').map(label => label.text())

  expect(labels).toEqual(['音色名称', '性别', '音频文件'])
  expect(wrapper.find('.app-dropzone').exists()).toBe(true)
  expect(wrapper.text()).toContain('点击选择音频文件')
  expect(wrapper.text()).toContain('也可以将音频文件拖拽到这里')
  expect(wrapper.text()).toContain('选择 1–30 秒音频，作为角色或旁白的声音参考')
  wrapper.unmount()
})

it('takes the file name and shows the picked file with its known metadata', async () => {
  const wrapper = render()
  const file = new File(['audio'], 'voice.mp3', { type: 'audio/mpeg' })

  await pickFile(wrapper, file)

  expect((wrapper.get('input#catalog-voice-name').element as HTMLInputElement).value).toBe('voice')
  expect(wrapper.get('.app-dropzone').text()).toContain('voice.mp3')
  expect(wrapper.get('.app-dropzone').text()).toContain('1 KB')
  wrapper.unmount()
})

it('keeps the existing size validation for oversized audio', async () => {
  const wrapper = render()
  const oversized = new File(['audio'], 'huge.wav', { type: 'audio/wav' })
  Object.defineProperty(oversized, 'size', { configurable: true, value: 201 * 1024 * 1024 })

  await pickFile(wrapper, oversized)

  expect(wrapper.get('[role="alert"]').text()).toContain('原音频不能超过 200MB')
  expect(wrapper.get('.app-dropzone').text()).not.toContain('huge.wav')
  wrapper.unmount()
})

it('uploads the reference clip with the entered name, gender and folder', async () => {
  vi.mocked(catalogApi.uploadVoice).mockResolvedValue({ data: {} } as never)
  const wrapper = render()
  const file = new File(['audio'], 'voice.mp3', { type: 'audio/mpeg' })
  await pickFile(wrapper, file)
  wrapper.findComponent(AudioRangeSlider).vm.$emit('loaded-duration', 5)
  await flushPromises()

  expect(wrapper.vm.valid).toBe(true)
  await wrapper.get('form').trigger('submit')
  await flushPromises()

  expect(catalogApi.uploadVoice).toHaveBeenCalledWith(file, 'voice', '未设置', 7, expect.any(Function))
  expect(wrapper.emitted('done')).toHaveLength(1)
  wrapper.unmount()
})
