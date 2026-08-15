import type {
  SupportedWorkbenchEdgeType,
  WorkbenchNode,
  WorkbenchNodeData,
  WorkbenchNodeKind,
} from '../types/workbenchTypes'

export interface WorkbenchHandleCapability {
  id: string
  label: string
  className: string
  type: 'source' | 'target'
  edgeType?: SupportedWorkbenchEdgeType
  role?: string
  required?: boolean
  minConnections?: number
  maxConnections?: number | null
}

const assetInput: WorkbenchHandleCapability = { id: 'asset-input', label: '资产输入端口', className: 'workbench-handle--asset', type: 'target' }
const sequenceInput: WorkbenchHandleCapability = { id: 'sequence-input', label: '视频顺序输入端口', className: 'workbench-handle--sequence', type: 'target' }
const outputInput: WorkbenchHandleCapability = { id: 'output-input', label: '结果输入端口', className: 'workbench-handle--output', type: 'target' }
const assetOutput: WorkbenchHandleCapability = { id: 'asset-output', label: '资产输出端口', className: 'workbench-handle--asset', type: 'source' }
const sequenceOutput: WorkbenchHandleCapability = { id: 'sequence-output', label: '视频顺序输出端口', className: 'workbench-handle--sequence', type: 'source' }
const outputOutput: WorkbenchHandleCapability = { id: 'output-output', label: '结果输出端口', className: 'workbench-handle--output', type: 'source' }
const watermarkInput: WorkbenchHandleCapability = { id: 'watermark-input', label: '水印配置', className: 'workbench-handle--watermark', type: 'target' }
const watermarkVideoInput: WorkbenchHandleCapability = { id: 'watermark-video-input', label: '视频输入', className: 'workbench-handle--output', type: 'target', required: true }
const watermarkOutput: WorkbenchHandleCapability = { id: 'watermark-output', label: '水印配置', className: 'workbench-handle--watermark', type: 'source' }
const composerShotInput: WorkbenchHandleCapability = { id: 'shot-input', label: '生成视频输入', className: 'workbench-handle--sequence', type: 'target' }
const composerVideoInput: WorkbenchHandleCapability = { id: 'video-input', label: '视频输入', className: 'workbench-handle--output', type: 'target' }

function configuredHandleClass(edgeType: SupportedWorkbenchEdgeType) {
  if (edgeType === 'asset_reference') return 'workbench-handle--asset'
  if (edgeType === 'shot_sequence') return 'workbench-handle--sequence'
  return 'workbench-handle--output'
}

export function configuredNodePorts(data?: Partial<WorkbenchNodeData>): WorkbenchHandleCapability[] {
  const ports = Array.isArray(data?.input_ports) ? data.input_ports : []
  return ports.flatMap((item) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return []
    const raw = item as Record<string, unknown>
    const id = typeof raw.id === 'string' ? raw.id : ''
    const direction = raw.direction === 'output' ? 'output' : raw.direction === 'input' ? 'input' : null
    const edgeType = ['asset_reference', 'shot_sequence', 'output_binding'].includes(String(raw.edge_type))
      ? raw.edge_type as SupportedWorkbenchEdgeType
      : null
    if (!id || !direction || !edgeType) return []
    return [{
      id,
      label: typeof raw.label === 'string' ? raw.label : id,
      className: configuredHandleClass(edgeType),
      type: direction === 'input' ? 'target' as const : 'source' as const,
      edgeType,
      role: typeof raw.role === 'string' ? raw.role : '',
      required: raw.required === true,
      minConnections: typeof raw.min_connections === 'number' ? raw.min_connections : 0,
      maxConnections: typeof raw.max_connections === 'number' ? raw.max_connections : null,
    }]
  })
}

export function workbenchNodeHandles(kind: WorkbenchNodeKind, data?: Partial<WorkbenchNodeData>) {
  const target: WorkbenchHandleCapability[] = []
  const source: WorkbenchHandleCapability[] = []
  const configured = configuredNodePorts(data)
  target.push(...configured.filter(handle => handle.type === 'target'))
  source.push(...configured.filter(handle => handle.type === 'source'))

  if (kind === 'asset') target.push({ ...assetInput, label: '参考图片' })
  if (kind === 'shot') target.push(assetInput, sequenceInput, watermarkInput)
  if (kind === 'video_result') target.push(outputInput)
  if (kind === 'watermark') target.push(watermarkVideoInput)
  if (kind === 'video_composer') target.push(composerShotInput, composerVideoInput, watermarkInput)

  if (['asset', 'audio_reference', 'digital_human', 'image_media', 'video_media', 'audio_media', 'video_result'].includes(kind)) {
    source.push(assetOutput)
  }
  if (kind === 'shot') source.push(sequenceOutput, outputOutput)
  if (kind === 'video_result' || kind === 'video_composer') source.push(outputOutput)
  if (kind === 'watermark') source.push(watermarkOutput, outputOutput)
  return { source: uniqueHandles(source), target: uniqueHandles(target) }
}

function uniqueHandles(handles: WorkbenchHandleCapability[]) {
  const seen = new Set<string>()
  return handles.filter((handle) => {
    const key = `${handle.type}:${handle.id}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

export function nodeExposesHandle(
  node: Pick<WorkbenchNode, 'kind' | 'data'> | null | undefined,
  handleId: string | null | undefined,
  type: WorkbenchHandleCapability['type'],
) {
  if (!node || !handleId) return false
  return workbenchNodeHandles(node.kind, node.data)[type].some(handle => handle.id === handleId)
}

export function classifyWorkbenchHandles(
  sourceHandle: string | null | undefined,
  targetHandle: string | null | undefined,
  sourceNode?: Pick<WorkbenchNode, 'kind' | 'data'> | null,
  targetNode?: Pick<WorkbenchNode, 'kind' | 'data'> | null,
): SupportedWorkbenchEdgeType | null {
  const configured = configuredNodePorts(targetNode?.data).find(handle => handle.type === 'target' && handle.id === targetHandle)
  if (configured?.edgeType) return configured.edgeType
  if (sourceHandle === 'asset-output'
    && targetHandle === 'asset-input'
    && sourceNode
    && ((targetNode?.kind === 'asset'
      && ['asset', 'digital_human', 'image_media'].includes(sourceNode.kind))
      || (targetNode?.kind === 'shot'
        && ['asset', 'digital_human', 'image_media', 'video_media', 'audio_media', 'audio_reference', 'video_result'].includes(sourceNode.kind)))) {
    return 'asset_reference'
  }
  if (sourceHandle === 'sequence-output'
    && targetHandle === 'sequence-input'
    && sourceNode?.kind === 'shot'
    && targetNode?.kind === 'shot') {
    return 'shot_sequence'
  }
  if (sourceHandle === 'watermark-output'
    && targetHandle === 'watermark-input'
    && sourceNode?.kind === 'watermark'
    && (targetNode?.kind === 'shot' || targetNode?.kind === 'video_composer')) {
    return 'output_binding'
  }
  if (sourceHandle === 'output-output'
    && targetHandle === 'watermark-video-input'
    && sourceNode
    && ['shot', 'video_result', 'video_media', 'video_composer', 'watermark'].includes(sourceNode.kind)
    && targetNode?.kind === 'watermark') {
    return 'output_binding'
  }
  if (sourceHandle === 'output-output'
    && targetHandle === 'output-input'
    && targetNode?.kind === 'video_result') {
    return 'output_binding'
  }
  if ((sourceHandle === 'sequence-output' && targetHandle === 'shot-input')
    || (sourceHandle === 'output-output' && targetHandle === 'video-input')) {
    return targetNode?.kind === 'video_composer' ? 'output_binding' : null
  }
  return null
}
