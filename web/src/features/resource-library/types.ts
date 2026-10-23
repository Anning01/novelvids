export interface ResourceFolder { id: number; parent_id: number; name: string; deleting: boolean }
export interface VideoResource {
  id: number; folder_id: number; name: string; filename: string; url: string; storage_ref: string
  poster_url: string; state: 'ready' | 'deleting' | 'delete_failed' | 'source'; created_at: string
  duration: number; width: number; height: number; fps: number; codec: string; content_type: string; size_bytes: number
}
export interface LibraryCapabilities { formats: string[]; max_size_mb: number; folder_depth: number }
export interface ResourceImport {
  source: 'video' | 'scene' | 'upload'; source_id: number; media_url?: string; folder_id?: number; name: string
}
export interface DeleteResult { id: number; deleted: boolean; error?: string }
