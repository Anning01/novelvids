import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getActiveTeamId, getAuthToken } from '@/api'
import type { AgentTarget } from './types'

export interface AgentTargetOption {
  target: AgentTarget
  label: string
  assetType?: number
}

export const targetKey = (target: AgentTarget) => `${target.kind}:${target.id}`

/** In-memory editing state shared by the production pages, separate from server runs. */
export const useCreationAgentWorkspace = defineStore('creation-agent-workspace', () => {
  const projectId = ref(0)
  const chapterId = ref(0)
  const isOpen = ref(false)
  const modelId = ref('')
  const selection = ref<AgentTargetOption[]>([])
  const scopeEdited = ref(false)
  const focusRevision = ref(0)
  const drafts = ref<Record<string, string>>({})
  let identity = ''

  function enterProject(id: number) {
    const nextIdentity = `${getAuthToken() || ''}:${getActiveTeamId() || ''}`
    if (id !== projectId.value || identity !== nextIdentity) {
      isOpen.value = false
      modelId.value = ''
      drafts.value = {}
      selection.value = []
      scopeEdited.value = false
      chapterId.value = 0
    }
    identity = nextIdentity
    projectId.value = id
  }

  function enterChapter(id: number) {
    if (chapterId.value === id) return
    chapterId.value = id
    selection.value = []
    scopeEdited.value = false
  }

  function select(options: AgentTargetOption[], edited = true) {
    selection.value = [...new Map(options.map(option => [targetKey(option.target), option])).values()]
    scopeEdited.value = edited
  }

  function editTargets(novelId: number, activeChapterId: number, options: AgentTargetOption[]) {
    enterProject(novelId)
    enterChapter(activeChapterId)
    select(options)
    isOpen.value = true
    focusRevision.value += 1
  }

  return { projectId, chapterId, isOpen, modelId, selection, scopeEdited, focusRevision, drafts,
    enterProject, enterChapter, select, editTargets }
})
