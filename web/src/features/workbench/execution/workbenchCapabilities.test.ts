import { expect, it } from 'vitest'
import type { WorkbenchCapabilities } from '@/types'
import { selectedRunState } from './workbenchCapabilities'
import { ref } from 'vue'
import { createWorkbenchNodeRunRegistry } from '../run/nodeRunRegistry'
import type { WorkbenchNode } from '../types/workbenchTypes'

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

it('shows the truthful watermark capability reason', () => {
  expect(selectedRunState([{
    id: -1,
    key: 'watermark-1',
    kind: 'watermark',
    backendKind: 'watermark',
    title: '新水印',
    position: { x: 0, y: 0 },
    size: null,
    zIndex: 1,
    activeVersionId: null,
    status: 'ready',
    data: { capability_key: 'apply_watermark', ui: {} },
    createdAt: '',
    updatedAt: '',
  }], capabilities)).toEqual({
    enabled: false,
    label: '运行所选配置',
    reason: '当前服务未启用水印执行',
    runnableKeys: [],
  })
})

it('shows the truthful composer capability reason', () => {
  expect(selectedRunState([{
    id: -2,
    key: 'composer-1',
    kind: 'video_composer',
    backendKind: 'video_composer',
    title: '视频合成器',
    position: { x: 0, y: 0 },
    size: null,
    zIndex: 1,
    activeVersionId: null,
    status: 'ready',
    data: { capability_key: 'compose_video', ui: {} },
    createdAt: '',
    updatedAt: '',
  }], capabilities)).toEqual({
    enabled: false,
    label: '运行所选配置',
    reason: '当前服务未启用视频合成',
    runnableKeys: [],
  })
})

it('uses the video card command for canvas execution and disables repeated submissions', () => {
  const node: WorkbenchNode = { id: -1, key: 'hd', kind: 'video_enhancement', backendKind: 'video_enhancement', title: '高清视频',
    position: { x: 0, y: 0 }, size: null, zIndex: 1, activeVersionId: null, status: 'ready', data: {}, createdAt: '', updatedAt: '' }
  const registry = createWorkbenchNodeRunRegistry()
  const enabled = ref(false)
  registry.register(node.key, { enabled, run: () => {} })
  expect(selectedRunState([node], capabilities, registry.commands).enabled).toBe(false)
  enabled.value = true
  expect(selectedRunState([node], capabilities, registry.commands)).toMatchObject({ enabled: true, runnableKeys: ['hd'] })
  enabled.value = false
  expect(selectedRunState([node], capabilities, registry.commands).enabled).toBe(false)
})
