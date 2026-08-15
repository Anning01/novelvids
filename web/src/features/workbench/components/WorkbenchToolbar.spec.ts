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
      watermarkEnabled: true,
      composerEnabled: true,
      runState: selectedRunState([], capabilities),
    },
  })

  await wrapper.get('[aria-label="添加节点"]').trigger('click')
  expect(wrapper.findAll('[role="menuitem"]').map(item => item.text())).toEqual([
    '资产',
    '视频',
    '便签',
    '水印',
    '视频合成器',
    '上传图片',
    '上传视频',
    '上传音频',
  ])

  expect(wrapper.find('[aria-label="复用项目资产"]').exists()).toBe(false)
})

it('keeps the three upload inputs visually hidden and emits every chosen file', async () => {
  const wrapper = mount(WorkbenchToolbar, {
    props: {
      running: false,
      runState: selectedRunState([], capabilities),
    },
  })

  expect(wrapper.findAll('input[type="file"]').map(input => input.attributes('aria-label'))).toEqual([
    '选择上传图片文件',
    '选择上传视频文件',
    '选择上传音频文件',
  ])
  expect(wrapper.findAll('input[type="file"]').map(input => input.attributes('accept'))).toEqual([
    'image/jpeg,image/png,image/webp,image/gif',
    'video/mp4,video/quicktime,.mp4,.mov',
    'audio/wav,audio/x-wav,audio/mpeg,.wav,.mp3',
  ])

  const firstFile = new File(['image'], 'photo.png', { type: 'image/png' })
  const secondFile = new File(['image'], 'photo-2.webp', { type: 'image/webp' })
  const imageInput = wrapper.get('input[accept^="image/"]')
  Object.defineProperty(imageInput.element, 'files', { configurable: true, value: [firstFile, secondFile] })
  await imageInput.trigger('change')

  expect(wrapper.emitted('uploadImage')).toEqual([[firstFile], [secondFile]])
})

it('emits the automatic layout action from the grid button', async () => {
  const wrapper = mount(WorkbenchToolbar, {
    props: {
      running: false,
      runState: selectedRunState([], capabilities),
    },
  })

  await wrapper.get('[aria-label="自动整理布局"]').trigger('click')

  expect(wrapper.emitted('auto-arrange')).toHaveLength(1)
})
