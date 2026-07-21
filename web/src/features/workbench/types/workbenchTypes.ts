export type WorkbenchNodeKind = 'chapter' | 'asset' | 'audio_reference' | 'digital_human' | 'shot' | 'video_result' | 'section' | 'note' | 'unsupported'
export type WorkbenchEdgeType = 'asset_reference' | 'shot_sequence' | 'output_binding' | 'unsupported'
export type SupportedWorkbenchEdgeType = Exclude<WorkbenchEdgeType, 'unsupported'>
export interface Point { x: number; y: number }
export interface NodeSize { width: number; height: number }
export interface WorkbenchViewport extends Point { zoom: number }
export interface WorkbenchNodeData { [key: string]: unknown; ui?: Record<string, unknown> }
export interface WorkbenchNode { id: number; key: string; kind: WorkbenchNodeKind; backendKind: string; title: string; position: Point; size: NodeSize | null; zIndex: number; activeVersionId: number | null; status: string; data: WorkbenchNodeData; createdAt: string; updatedAt: string }
export interface WorkbenchEdge { id: number; key: string; source: string; target: string; type: WorkbenchEdgeType; backendType: string; sourceHandle: string | null; targetHandle: string | null; orderIndex: number; config: Record<string, unknown> | null; createdAt: string; updatedAt: string }
