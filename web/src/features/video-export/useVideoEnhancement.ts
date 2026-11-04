import { computed, onMounted, onUnmounted, ref, shallowRef, watch, type Ref } from 'vue'
import { api, API_BASE, authHeaders, mediaUrl } from '@/api'
import { useAuthStore } from '@/features/auth/authStore'
import { tr } from '@/i18n'
import { downloadFile } from '@/shared/downloadFile'
import { videoPixelSize } from '@/features/workbench/graph/videoMedia'
import type { Video } from '@/types'
import { exportApi, type ChapterExport, type EnhancementModel, type ExportQuote } from './api'

const running = (row?: ChapterExport) => Boolean(row && ([1, 2, 6].includes(row.status || 0) || row.stage === 'billing_pending'))

export function useVideoEnhancement(video: Readonly<Ref<Video>>, visible: Readonly<Ref<boolean>>, applied: (id: number) => void,
  pixelSize?: Readonly<Ref<{ width: number; height: number } | null | undefined>>) {
  const auth = useAuthStore()
  const rows = ref<ChapterExport[]>([])
  const models = ref<EnhancementModel[]>([])
  const modelId = ref('')
  const resolution = ref('')
  const loadingModels = ref(true), loadingHistory = ref(true), preparing = ref(false), submitting = ref(false)
  const modelError = ref(''), historyError = ref(''), actionError = ref(''), quoteError = ref('')
  const quote = shallowRef<ExportQuote | null>(null)
  const submittedQuote = shallowRef<ExportQuote | null>(null)
  let quotedKey = ''
  const quoting = ref(false), uncertain = ref(false), submittedId = ref(0)
  const awaitingSource = ref(false)
  const resultVideo = shallowRef<Video | null>(null)
  const source = computed(() => rows.value.find(row => !row.parent_export_id))
  const run = computed(() => rows.value.find(row => row.id === submittedId.value)
    || rows.value.find(row => row.parent_export_id && (running(row) || row.stage === 'needs_review' || row.applied_to_scene)))
  const canWrite = computed(() => auth.enabled !== true || auth.isSuperAdmin || ['admin', 'creator'].includes(auth.role || ''))
  const scope = computed(() => `${video.value.id}:${auth.activeTeamId}:${auth.user?.id}:${auth.role}`)
  const model = computed(() => models.value.find(item => String(item.id) === modelId.value))
  const size = computed(() => source.value?.source_probe.width && source.value.source_probe.height
    ? { width: source.value.source_probe.width, height: source.value.source_probe.height } : pixelSize?.value || videoPixelSize(video.value))
  const shortSide = computed(() => size.value ? Math.min(size.value.width, size.value.height) : 0)
  const resolutions = computed(() => (model.value?.supported_resolutions || model.value?.resolutions || []).map(item => ({
    ...item, disabled: item.short_side <= shortSide.value || !model.value?.resolutions.some(enabled => enabled.value === item.value),
    reason: item.short_side <= shortSide.value ? tr('不高于原片') : !model.value?.resolutions.some(enabled => enabled.value === item.value) ? tr('服务未启用') : '',
  })))
  const target = computed(() => resolutions.value.find(item => item.value === resolution.value))
  const locked = computed(() => submitting.value || Boolean(run.value) || uncertain.value)
  const sourceReady = computed(() => source.value?.status === 3 && Boolean(source.value.source_sha256))
  const quoteKey = computed(() => canWrite.value && sourceReady.value && model.value && target.value && !target.value.disabled && !locked.value
    && !(model.value.input_short_side_max && shortSide.value > model.value.input_short_side_max)
    ? `${scope.value}:${source.value!.id}:${source.value!.source_sha256}:${modelId.value}:${resolution.value}` : '')
  const background = computed(() => preparing.value || awaitingSource.value || submitting.value || uncertain.value || running(source.value) || running(run.value)
    || Boolean(submittedId.value && !run.value))
  const error = computed(() => actionError.value || historyError.value || modelError.value || quoteError.value)
  let alive = true, generation = 0, quoteRevision = 0, modelRevision = 0, historyRevision = 0, historyBusy = false, prepareAttempted = false
  let interval: ReturnType<typeof setInterval> | undefined
  const reported = new Set<number>()
  let resultRequested = 0
  const valid = (revision: number, current: string) => alive && revision === generation && current === scope.value

  watch([modelId, shortSide, resolutions], () => {
    if (!target.value || target.value.disabled) resolution.value = resolutions.value.find(item => !item.disabled)?.value || ''
  })

  async function fetchQuote() {
    const key = quoteKey.value, revision = ++quoteRevision
    quote.value = null; quotedKey = ''; quoteError.value = ''; quoting.value = Boolean(key)
    if (!key) return
    try {
      const response = await exportApi.quote(source.value!.id, Number(modelId.value), resolution.value)
      if (alive && revision === quoteRevision && key === quoteKey.value) { quote.value = response.data; quotedKey = key }
    } catch (caught) {
      if (alive && revision === quoteRevision && key === quoteKey.value) quoteError.value = (caught as Error).message
    } finally { if (alive && revision === quoteRevision) quoting.value = false }
  }
  watch(quoteKey, () => { void fetchQuote() })

  async function readResult(row: ChapterExport, revision: number, current: string) {
    const id = row.result_video_id
    if (!id || resultRequested === id || resultVideo.value?.id === id) return
    resultRequested = id
    try {
      // The ordinary scoped video API exposes the playable media URL; no full Blob fetch.
      const result = await api.videos(video.value.scene_id)
      if (!valid(revision, current) || run.value?.result_video_id !== id) return
      resultVideo.value = result.data.items.find(item => item.id === id && item.status === 3) || null
    } catch { /* Keep the original preview and authenticated history download available. */ }
    finally { if (valid(revision, current)) resultRequested = 0 }
  }

  async function loadHistory() {
    if (historyBusy) return
    const revision = generation, current = scope.value, historyVersion = ++historyRevision
    historyBusy = true
    try {
      const response = await exportApi.listVideo(video.value.id)
      if (!valid(revision, current) || historyVersion !== historyRevision) return
      rows.value = response.data
      if (source.value) awaitingSource.value = false
      historyError.value = ''
      if (run.value) uncertain.value = false
      for (const row of rows.value) {
        if (row.applied_to_scene && row.result_video_id && !reported.has(row.result_video_id)) {
          reported.add(row.result_video_id)
          applied(row.result_video_id)
        }
      }
      if (run.value?.status === 3 && run.value.result_video_id) void readResult(run.value, revision, current)
    } catch (caught) {
      if (valid(revision, current) && historyVersion === historyRevision) historyError.value = (caught as Error).message
    } finally { if (valid(revision, current) && historyVersion === historyRevision) { historyBusy = false; loadingHistory.value = false } }
  }

  function invalidateHistory() { historyRevision++; historyBusy = false }

  async function loadModels() {
    const revision = generation, current = scope.value, version = ++modelRevision
    loadingModels.value = true
    try {
      const response = await exportApi.models()
      if (!valid(revision, current) || version !== modelRevision) return
      models.value = response.data; modelError.value = ''
      if (!model.value) modelId.value = String(models.value[0]?.id || '')
    } catch (caught) { if (valid(revision, current) && version === modelRevision) modelError.value = (caught as Error).message }
    finally { if (valid(revision, current) && version === modelRevision) loadingModels.value = false }
  }

  async function prepare() {
    if (prepareAttempted || loadingHistory.value || loadingModels.value || historyBusy || rows.value.length || historyError.value || !models.value.length || !canWrite.value) return
    const revision = generation, current = scope.value
    prepareAttempted = true; preparing.value = true; awaitingSource.value = true
    try {
      await exportApi.prepareVideo(video.value.id)
      if (valid(revision, current)) { invalidateHistory(); await loadHistory() }
    } catch (caught) { if (valid(revision, current)) { actionError.value = (caught as Error).message; awaitingSource.value = false } }
    finally { if (valid(revision, current)) preparing.value = false }
  }

  async function refresh() {
    const retryPreparation = Boolean(actionError.value) && !uncertain.value
    actionError.value = ''
    const revision = generation, current = scope.value
    await Promise.all([loadHistory(), (!models.value.length || modelError.value) ? loadModels() : Promise.resolve()])
    if (valid(revision, current)) {
      if (retryPreparation && !rows.value.length && !historyError.value) prepareAttempted = false
      await prepare()
    }
  }

  async function apply(row: ChapterExport) {
    if (submitting.value || !canWrite.value) return
    const revision = generation, current = scope.value
    submitting.value = true; actionError.value = ''
    try {
      const response = await exportApi.apply(row.id)
      if (!valid(revision, current)) return
      submittedId.value = row.id; resultVideo.value = response.data
      reported.add(response.data.id)
      applied(response.data.id)
      invalidateHistory()
      await loadHistory()
    } catch (caught) { if (valid(revision, current)) actionError.value = (caught as Error).message }
    finally { if (valid(revision, current)) submitting.value = false }
  }

  async function restoreOriginal() {
    if (submitting.value || !canWrite.value || background.value) return
    const revision = generation, current = scope.value
    submitting.value = true; actionError.value = ''
    try {
      const response = await api.selectCurrentVideo(video.value.id)
      if (!valid(revision, current)) return
      submittedId.value = 0; resultVideo.value = null; submittedQuote.value = null
      rows.value = rows.value.map(row => ({ ...row, applied_to_scene: false }))
      applied(response.data.id)
      invalidateHistory(); await loadHistory()
    } catch (caught) { if (valid(revision, current)) actionError.value = (caught as Error).message }
    finally { if (valid(revision, current)) submitting.value = false }
  }

  async function submit() {
    const confirmedQuote = quote.value, confirmedSource = source.value, key = quoteKey.value
    if (!key || key !== quotedKey || !confirmedQuote || !confirmedSource || confirmedQuote.source_sha256 !== confirmedSource.source_sha256 || submitting.value || error.value) return
    if (confirmedQuote.reused_export_id) {
      const existing = rows.value.find(row => row.id === confirmedQuote.reused_export_id)
      if (existing) await apply(existing)
      else { actionError.value = tr('已有高清版本信息已变化，请刷新后重试'); await loadHistory() }
      return
    }
    const revision = generation, current = scope.value, selectedModel = Number(modelId.value), selectedResolution = resolution.value
    submittedQuote.value = confirmedQuote
    submitting.value = true; actionError.value = ''
    try {
      // The inline confirmation submits exactly the source, model, target and quote the user saw.
      const response = await exportApi.enhance(confirmedSource.id, selectedModel, confirmedQuote, selectedResolution)
      if (!valid(revision, current)) return
      submittedId.value = response.data.export_id
      invalidateHistory()
      await loadHistory()
    } catch (caught) {
      if (!valid(revision, current)) return
      uncertain.value = true; actionError.value = (caught as Error).message
      invalidateHistory()
      await loadHistory()
    } finally { if (valid(revision, current)) submitting.value = false }
  }

  async function download(row?: ChapterExport) {
    const revision = generation, current = scope.value
    try {
      if (row) await downloadFile(`${API_BASE}/video/exports/${row.id}/download`, `video-${video.value.id}-${row.parent_export_id ? row.recipe.resolution || 'hd' : 'source'}.mp4`, authHeaders())
      else if (video.value.url) await downloadFile(mediaUrl(video.value.url), `video-${video.value.id}.mp4`)
    } catch (caught) { if (valid(revision, current)) actionError.value = (caught as Error).message }
  }

  async function initialize() {
    const revision = generation, current = scope.value
    quote.value = null; quotedKey = ''; quoteError.value = ''; quoteRevision++; quoting.value = false
    await Promise.all([loadModels(), loadHistory()])
    if (valid(revision, current)) {
      await prepare()
      if (quoteKey.value && !quote.value && !quoting.value && !quoteError.value) await fetchQuote()
    }
  }
  watch(scope, () => {
    generation++; quoteRevision++; invalidateHistory(); prepareAttempted = false
    rows.value = []; models.value = []; quote.value = null; submittedQuote.value = null; resultVideo.value = null; submittedId.value = 0
    resultRequested = 0
    uncertain.value = false; submitting.value = false; preparing.value = false; awaitingSource.value = false; loadingHistory.value = true
    modelError.value = ''; historyError.value = ''; actionError.value = ''; reported.clear()
    void initialize()
  })
  watch(visible, value => { if (value) void initialize() })
  function focus() { if (visible.value && document.visibilityState !== 'hidden') void initialize() }
  onMounted(() => {
    void initialize(); window.addEventListener('focus', focus)
    interval = setInterval(() => { if (background.value && document.visibilityState !== 'hidden') void loadHistory() }, 5000)
  })
  onUnmounted(() => { alive = false; generation++; quoteRevision++; clearInterval(interval); window.removeEventListener('focus', focus) })
  return { rows, models, modelId, resolution, source, run, model, size, shortSide, target, resolutions, locked,
    loadingModels, loadingHistory, preparing, submitting, quoting, uncertain, submittedId, quote, error, quoteError,
    canWrite, background, resultVideo, sourceReady, submittedQuote, fetchQuote, refresh, submit, apply, restoreOriginal, download }
}
