import type { WorkbenchCapabilities } from '@/types'
import type { WorkbenchNode } from '../types/workbenchTypes'

export interface WorkbenchRunState {
  enabled: boolean
  label: '请先选择可执行节点' | '运行所选配置'
  reason: string
  runnableKeys: string[]
}

export function selectedRunState(
  nodes: WorkbenchNode[],
  capabilities: WorkbenchCapabilities,
): WorkbenchRunState {
  if (!nodes.length) {
    return {
      enabled: false,
      label: '请先选择可执行节点',
      reason: '请选择资产、镜头、水印或视频合成节点',
      runnableKeys: [],
    }
  }

  const runnableKeys: string[] = []
  for (const node of nodes) {
    if ((node.data.ui as Record<string, unknown> | undefined)?.ignored === true) {
      return { enabled: false, label: '运行所选配置', reason: `${node.title}已被忽略`, runnableKeys }
    }
    const capabilityKey = typeof node.data.capability_key === 'string' ? node.data.capability_key : ''
    if (node.kind === 'asset') {
      if (!capabilities.generate_asset) return { enabled: false, label: '运行所选配置', reason: '当前服务不支持资产生成', runnableKeys }
      if (!node.data.asset) return { enabled: false, label: '运行所选配置', reason: `${node.title}缺少资产配置`, runnableKeys }
    } else if (node.kind === 'shot') {
      if (!capabilities.generate_video) return { enabled: false, label: '运行所选配置', reason: '当前服务不支持视频生成', runnableKeys }
      if (!node.data.scene) return { enabled: false, label: '运行所选配置', reason: `${node.title}缺少镜头配置`, runnableKeys }
    } else if (capabilityKey === 'apply_watermark') {
      if (!capabilities.apply_watermark) return { enabled: false, label: '运行所选配置', reason: '当前服务不支持水印处理', runnableKeys }
    } else if (capabilityKey === 'compose_video') {
      if (!capabilities.compose_video) return { enabled: false, label: '运行所选配置', reason: '当前服务不支持视频合成', runnableKeys }
    } else {
      return { enabled: false, label: '运行所选配置', reason: `${node.title}不是可执行节点`, runnableKeys }
    }
    runnableKeys.push(node.key)
  }

  return {
    enabled: runnableKeys.length > 0,
    label: '运行所选配置',
    reason: runnableKeys.length ? '' : '请选择资产、镜头、水印或视频合成节点',
    runnableKeys,
  }
}
