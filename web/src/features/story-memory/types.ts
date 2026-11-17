export type MemoryState = 'missing' | 'current' | 'stale'
export interface MemoryChapter {
  chapter_id: number | null
  number: number | null
  commit_id: number | null
  state: MemoryState
  reason: string | null
  can_analyze: boolean
  blocked_by: string | null
}
export interface MemoryStatus { baseline: MemoryChapter; chapters: MemoryChapter[] }
export interface MemoryEvidence { source: string; start: number; end: number; quote: string }
export interface MemorySubject { ref: string; existing_id: number | null; kind: string; name: string; aliases: string[] }
export interface MemoryScope { world_ref: string | null; scene: string | null; from_chapter: number | null; until_chapter: number | null; story_time: string | null }
export type FactNature = 'fact' | 'testimony' | 'inference' | 'plan' | 'creative_decision'
export interface MemoryFact {
  subject_ref: string
  category: string
  nature: FactNature
  content: string
  scope: MemoryScope
  evidence: MemoryEvidence[]
  operation: 'add' | 'replace' | 'retract'
  replaces_id: number | null
}
export interface MemoryCandidate { subjects: MemorySubject[]; facts: MemoryFact[]; summary: string; ending_state: string; unresolved: string[] }
export interface MemoryCommit {
  id: number
  chapter_id: number | null
  status: 'pending' | 'draft' | 'ready' | 'needs_review' | 'accepted' | 'rejected' | 'stale'
  revision: number
  package_hash: string
  current: boolean
  stale_reason: string | null
  task_id: string | null
  created_at: string
  decided_at: string | null
}
export interface MemoryDetail extends MemoryCommit {
  candidate: MemoryCandidate | Record<string, never>
  review: { issues?: { severity: 'blocking' | 'warning'; fact_index: number | null; reason: string }[]; summary?: string }
  recheck_task_id: string | null
  replaced_facts?: Record<number, string>
}
export interface MemoryContextFact {
  id: number
  subject: { id: number; kind: string; name: string; aliases: string[] }
  category: string
  nature: FactNature
  content: string
  evidence: MemoryEvidence[]
  scope: Record<string, string | number | null>
}
export interface MemoryContext {
  enabled: boolean
  facts?: MemoryContextFact[]
  baseline_summary?: string
  worlds?: { id: number; name: string }[]
  previous?: { summary: string; ending_state: string } | null
  current?: { summary: string; ending_state: string; unresolved: string[] }
}
