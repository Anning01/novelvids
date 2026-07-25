import { expect, it } from 'vitest'
import type { WorkbenchCapabilities } from '@/types'
import { selectedRunState } from './workbenchCapabilities'

const capabilities: WorkbenchCapabilities = {
  upload_media: true,
  generate_asset: true,
  generate_video: true,
  apply_watermark: false,
  compose_video: false,
}

it('disables the CTA when selection is empty', () => {
  expect(selectedRunState([], capabilities)).toEqual({
    enabled: false,
    label: '请先选择可执行节点',
    reason: '请选择资产、镜头、水印或视频合成节点',
    runnableKeys: [],
  })
})
