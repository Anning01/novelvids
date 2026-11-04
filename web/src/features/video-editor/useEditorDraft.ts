import { computed, onBeforeUnmount, ref, shallowRef } from 'vue'
import { ApiRequestError } from '@/api'
import { tr } from '@/i18n'
import { editorApi } from './api'
import { cloneDocument, compactVideoTrack, validateDocument } from './model'
import type { EditDocument, EditorDraft, EditorMedia } from './types'

export function useEditorDraft(identity: () => string) {
  const document = shallowRef<EditDocument | null>(null)
  const media = ref<EditorMedia[]>([]), selectedId = ref(''), revision = ref(0)
  const loading = ref(false), saving = ref(false), error = ref(''), saveError = ref(''), conflict = ref(false)
  const baseline = ref(''), recovery = shallowRef<EditDocument | null>(null)
  const undoStack = ref<string[]>([]), redoStack = ref<string[]>([])
  let chapterId = 0, scope = 0, disposed = false, timer: ReturnType<typeof setTimeout> | undefined
  let inFlight: Promise<boolean> | null = null, controller: AbortController | null = null
  const dirty = computed(() => document.value !== null && JSON.stringify(document.value) !== baseline.value)
  const selected = computed(() => document.value?.clips.find(clip => clip.id === selectedId.value) || null)
  const storageKey = () => `novelvids-editor-v1:${identity()}:${chapterId}`
  function bounds(value: EditDocument) {
    if (value.clips.length > 500) throw new Error(tr('片段数量超过服务端限制'))
    return validateDocument(value)
  }

  function backup() {
    if (!document.value) return
    try {
      if (dirty.value) sessionStorage.setItem(storageKey(), JSON.stringify({ revision: revision.value, document: document.value }))
      else sessionStorage.removeItem(storageKey())
    } catch { /* Keep unsaved edits in memory if browser storage is full or unavailable. */ }
  }
  async function load(id: number) {
    const version = ++scope; chapterId = id; controller?.abort(); clearTimeout(timer); inFlight = null
    controller = new AbortController(); loading.value = true; error.value = ''; saveError.value = ''; conflict.value = false
    document.value = null; media.value = []; saving.value = false; undoStack.value = []; redoStack.value = []; recovery.value = null
    try {
      const response = await editorApi.get(id, controller.signal)
      if (version !== scope || disposed) return
      install(response.data)
      try {
        const raw = sessionStorage.getItem(storageKey())
        if (raw) {
          const local = JSON.parse(raw) as { revision: number; document: EditDocument }
          validateDocument(local.document)
          if (JSON.stringify(local.document) !== baseline.value) recovery.value = local.document
        }
      } catch { /* Invalid old browser drafts must not prevent reading the saved version. */ }
    } catch (reason) { if (version === scope && !disposed && !(reason instanceof DOMException && reason.name === 'AbortError')) error.value = reason instanceof Error ? reason.message : tr('剪辑工作区读取失败') }
    finally { if (version === scope && !disposed) loading.value = false }
  }
  function install(value: EditorDraft) {
    document.value = cloneDocument(value.document); baseline.value = JSON.stringify(value.document)
    media.value = value.media; revision.value = value.revision
    selectedId.value = value.document.clips[0]?.id || ''
  }
  function schedule() { clearTimeout(timer); if (!conflict.value) timer = setTimeout(() => { void save() }, 800) }
  function commit(next: EditDocument, nextSelectedId?: string) {
    next = compactVideoTrack(next)
    bounds(next)
    if (JSON.stringify(next) === JSON.stringify(document.value)) return
    if (document.value) undoStack.value.push(JSON.stringify(document.value))
    undoStack.value = undoStack.value.slice(-60); redoStack.value = []
    document.value = cloneDocument(next); if (nextSelectedId !== undefined) selectedId.value = nextSelectedId
    saveError.value = ''; backup(); schedule()
  }
  function history(from: typeof undoStack, to: typeof redoStack) {
    if (!from.value.length || !document.value) return
    to.value.push(JSON.stringify(document.value)); document.value = JSON.parse(from.value.pop()!) as EditDocument
    if (!document.value.clips.some(c => c.id === selectedId.value)) selectedId.value = document.value.clips[0]?.id || ''
    backup(); schedule()
  }
  async function save(): Promise<boolean> {
    clearTimeout(timer)
    if (inFlight) { const result = await inFlight; return result && dirty.value ? save() : result }
    if (!document.value || conflict.value || disposed) return false
    if (!dirty.value && revision.value > 0) return true
    const version = scope, id = chapterId, value = cloneDocument(document.value), serialized = JSON.stringify(value)
    saving.value = true; saveError.value = ''
    const pending = (async () => {
      try {
        const response = await editorApi.save(id, revision.value, value)
        if (version !== scope || disposed) return false
        revision.value = response.data.revision
        baseline.value = JSON.stringify(response.data.document || value)
        if (JSON.stringify(document.value) === serialized) document.value = cloneDocument(response.data.document || value)
        backup(); return true
      } catch (reason) {
        if (version === scope && !disposed) {
          conflict.value = reason instanceof ApiRequestError && reason.code === 409
          saveError.value = reason instanceof Error ? reason.message : tr('剪辑草稿保存失败')
          backup()
        }
        return false
      } finally { if (version === scope && !disposed) { saving.value = false; inFlight = null } }
    })()
    inFlight = pending
    return pending
  }
  function addMedia(item: EditorMedia) { media.value = [...media.value.filter(old => old.key !== item.key), item] }
  function recoverLocal() { if (recovery.value) { commit(recovery.value); recovery.value = null } }
  function ignoreRecovery() { recovery.value = null; try { sessionStorage.removeItem(storageKey()) } catch { /* Optional recovery storage. */ } }
  function unload(event: BeforeUnloadEvent) { if (dirty.value) { backup(); event.preventDefault(); event.returnValue = '' } }
  window.addEventListener('beforeunload', unload)
  onBeforeUnmount(() => { backup(); disposed = true; ++scope; clearTimeout(timer); controller?.abort(); window.removeEventListener('beforeunload', unload) })
  return { document, media, selectedId, selected, revision, loading, saving, error, saveError, conflict, dirty, recovery,
    undoStack, redoStack, load, commit, save, addMedia, recoverLocal, ignoreRecovery,
    undo: () => history(undoStack, redoStack), redo: () => history(redoStack, undoStack) }
}
