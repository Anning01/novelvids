import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import type { WorkbenchCapabilities } from '@/types'
import { selectedRunState } from '../execution/workbenchCapabilities'
import WorkbenchToolbar from './WorkbenchToolbar.vue'

const capabilities: WorkbenchCapabilities = {
  upload_media: true,
  generate_asset: true,
  generate_video: true,
  apply_watermark: false,
  compose_video: false,
}

it('shows every verified add menu item in order', async () => {
  const wrapper = mount(WorkbenchToolbar, {
    props: {
      running: false,
      canUndo: false,
      canRedo: false,
      hasSelection: false,
      canCopy: false,
      canPaste: false,
      canCreateSection: false,
      runState: selectedRunState([], capabilities),
    },
  })

  await wrapper.get('[aria-label="添加节点"]').trigger('click')
  expect(wrapper.findAll('[role="menuitem"]').map(item => item.text())).toEqual([
    '空资产',
    '镜头',
    '便签',
    '水印',
    '视频合成',
    '上传图片',
    '上传视频',
    '上传音频',
    '参考音频',
    '数字人',
  ])
})

it('exposes the three direct upload buttons and emits the chosen file', async () => {
  const wrapper = mount(WorkbenchToolbar, {
    props: {
      running: false,
      runState: selectedRunState([], capabilities),
    },
  })

  expect(wrapper.findAll('button').filter(button => button.attributes('aria-label')?.startsWith('选择上传')).map(button => button.attributes('aria-label'))).toEqual([
    '选择上传图片文件',
    '选择上传视频文件',
    '选择上传音频文件',
  ])
  expect(wrapper.findAll('input[type="file"]').map(input => input.attributes('accept'))).toEqual([
    'image/png,image/jpeg,image/webp',
    'video/mp4,video/webm,video/quicktime',
    'audio/mpeg,audio/wav,audio/mp4,audio/webm',
  ])

  const file = new File(['image'], 'photo.png', { type: 'image/png' })
  const imageInput = wrapper.get('input[accept^="image/"]')
  Object.defineProperty(imageInput.element, 'files', { configurable: true, value: [file] })
  await imageInput.trigger('change')

  expect(wrapper.emitted('uploadImage')).toEqual([[file]])
})
