import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import AppFileDropzone from './AppFileDropzone.vue'

function audioFile(name = 'voice.mp3') {
  return new File(['audio'], name, { type: 'audio/mpeg' })
}

it('replaces the native control with a drop zone that explains both entry points', () => {
  const wrapper = mount(AppFileDropzone, { props: { title: '点击选择音频文件', hint: '也可以将音频文件拖拽到这里' } })

  expect(wrapper.find('.app-dropzone').exists()).toBe(true)
  expect(wrapper.text()).toContain('点击选择音频文件')
  expect(wrapper.text()).toContain('也可以将音频文件拖拽到这里')
  expect(wrapper.get('input[type="file"]').classes()).toContain('app-dropzone__input')
  wrapper.unmount()
})

it('emits the picked files and clears the native input so the same file can be picked again', async () => {
  const wrapper = mount(AppFileDropzone)
  const input = wrapper.get('input[type="file"]')
  const selected = audioFile()
  Object.defineProperty(input.element, 'files', { configurable: true, value: [selected] })

  await input.trigger('change')

  expect(wrapper.emitted('select')).toHaveLength(1)
  expect(wrapper.emitted('select')![0][0]).toEqual([selected])
  wrapper.unmount()
})

it('accepts files that are dragged onto the drop zone', async () => {
  const wrapper = mount(AppFileDropzone)
  const dropped = audioFile('drag.wav')

  await wrapper.get('.app-dropzone').trigger('drop', { dataTransfer: { files: [dropped] } })

  expect(wrapper.emitted('select')).toHaveLength(1)
  expect(wrapper.emitted('select')![0][0]).toEqual([dropped])
  wrapper.unmount()
})

it('ignores dropped files while the drop zone is disabled', async () => {
  const wrapper = mount(AppFileDropzone, { props: { disabled: true } })

  await wrapper.get('.app-dropzone').trigger('drop', { dataTransfer: { files: [audioFile()] } })

  expect(wrapper.emitted('select')).toBeUndefined()
  wrapper.unmount()
})

it('shows the selected file name with the metadata that is already known', () => {
  const wrapper = mount(AppFileDropzone, { props: { fileName: 'voice.mp3', meta: '1.20 MB · 0:03' } })

  expect(wrapper.text()).toContain('voice.mp3')
  expect(wrapper.text()).toContain('1.20 MB · 0:03')
  wrapper.unmount()
})
