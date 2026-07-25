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
