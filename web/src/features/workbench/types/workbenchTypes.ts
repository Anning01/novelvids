export type WorkbenchNodeKind = 'chapter' | 'source_video' | 'ai_decomposition' | 'asset' | 'audio_reference' | 'digital_human' | 'image_media' | 'video_media' | 'audio_media' | 'shot' | 'video_result' | 'watermark' | 'video_composer' | 'section' | 'note' | 'unsupported'
export type WorkbenchEdgeType = 'asset_reference' | 'shot_sequence' | 'output_binding' | 'unsupported'
export type SupportedWorkbenchEdgeType = Exclude<WorkbenchEdgeType, 'unsupported'>
export interface Point { x: number; y: number }
export interface NodeSize { width: number; height: number }
export interface WorkbenchViewport extends Point { zoom: number }
export type JSONPrimitive = string | number | boolean | null
export type JSONValue = JSONPrimitive | JSONObject | JSONValue[]
export interface JSONObject { [key: string]: JSONValue }
export type JsonRecord = JSONObject
export type ImageAnnotationTool = 'rectangle' | 'ellipse' | 'grid' | 'arrow' | 'freehand'
export interface ImageAnnotation { id: string; tool: ImageAnnotationTool; points: Point[]; stroke: string; strokeWidth: number }
export interface UploadedMediaData {
  url: string
  filename: string
  originalFilename: string
  mimeType: string
  width?: number
  height?: number
  durationSeconds?: number
  annotations?: ImageAnnotation[]
}
export interface WorkbenchPromptEditor {
  editorKey: string
  nodeKind: 'asset' | 'shot'
  fieldKey: string
  label: string
  placeholder: string
  hint: string
  allowedAssetTypes: string[] | null
  excludedAssetTypes: string[] | null
  referenceLimits: {
    image: number
    video: number
    audio: number
  }
  allowPromptInjection: boolean
}
export interface WorkbenchNodeData {
  [key: string]: unknown
  ui?: Record<string, unknown>
  draftPrompt?: string
  assetType?: string
}
export interface AssetReferenceEdgeConfig {
  [key: string]: unknown
  strategy?: 'follow_primary' | 'locked_version'
  versionId?: number
  inputMode?: 'auto' | 'prompt_injection' | 'reference_image' | 'reference_video' | 'reference_audio'
  annotatedImageUrl?: string
}
export interface WorkbenchNode { id: number; key: string; kind: WorkbenchNodeKind; backendKind: string; title: string; position: Point; size: NodeSize | null; zIndex: number; activeVersionId: number | null; status: string; data: WorkbenchNodeData; createdAt: string; updatedAt: string }
export interface WorkbenchEdge { id: number; key: string; source: string; target: string; type: WorkbenchEdgeType; backendType: string; sourceHandle: string | null; targetHandle: string | null; orderIndex: number; config: Record<string, unknown> | null; createdAt: string; updatedAt: string }
