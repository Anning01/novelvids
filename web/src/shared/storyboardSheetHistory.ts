export interface SheetHistoryItem {
  task_id: string
  source: boolean
  image_url: string
  is_current: boolean
  instruction: string
  created_at: string
  model?: string
  saved: boolean
}
export interface SheetHistory {
  scene_id: number
  revision: string
  current_image_url: string
  items: SheetHistoryItem[]
}
