<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, toRaw, useId, watch } from 'vue'
import { BookOpen, RefreshCw, X } from 'lucide-vue-next'
import { api } from '@/api'
import { tr } from '@/i18n'
import { notice } from '@/shared/notice'
import type { AiTask } from '@/types'
import AppButton from '@/components/AppButton.vue'
import AppBadge from '@/components/AppBadge.vue'
import AppSelect from '@/components/AppSelect.vue'
import TaskSkillPicker from '@/features/creation-agent/TaskSkillPicker.vue'
import { storyMemoryApi } from './api'
import type { FactNature, MemoryCandidate, MemoryCommit, MemoryContext, MemoryDetail, MemoryScope, MemoryStatus } from './types'

const props = defineProps<{ projectId: number; chapterId?: number; canEdit: boolean; disabled?: boolean;
  reviewTarget?: HTMLElement | null; refreshKey?: number; modelsLoading?: boolean; models: { value: string; label: string }[] }>()
const emit = defineEmits<{ showRun: [run?: { taskId: string; conversationId: number }] }>()
const modelId = defineModel<string>('modelId', { default: '' })
const skillId = defineModel<number>('skillId')
const id = useId()
const status = ref<MemoryStatus | null>(null)
const commits = ref<MemoryCommit[]>([])
const detail = ref<MemoryDetail | null>(null)
const context = ref<MemoryContext | null>(null)
const draft = ref<MemoryCandidate | null>(null)
const scope = ref('baseline')
const loading = ref(false)
const busy = ref(false)
const decisionNote = ref('')
const job = ref<AiTask | null>(null)
const shownFacts = ref(20)
const memoryDialog = ref<HTMLDialogElement | null>(null)
const memoryOpen = ref(false)
let requests = new AbortController()
let epoch = 0
let selection = 0
let refresh = 0
let pollRevision = 0
let scopeRevision = 0
let requestedRun: string | undefined
let timer: ReturnType<typeof setTimeout> | undefined
const chapterId = computed(() => scope.value === 'baseline' ? null : Number(scope.value))
const rows = computed(() => status.value ? [status.value.baseline, ...status.value.chapters] : [])
const selected = computed(() => rows.value.find(row => row.chapter_id === chapterId.value))
const running = computed(() => job.value && [1, 2, 6].includes(job.value.status) && job.value.stage !== 'needs_review')
const locked = computed(() => busy.value || Boolean(running.value) || props.disabled)
const candidate = computed(() => detail.value && Array.isArray(detail.value.candidate.facts) ? detail.value.candidate as MemoryCandidate : null)
const hasCandidate = computed(() => candidate.value !== null && detail.value?.status !== 'accepted')
const emptyBaseline = computed(() => detail.value?.chapter_id === null && candidate.value?.facts.length === 0)
const focusReview = ref(false)
const editable = computed(() => props.canEdit && detail.value?.current && ['draft', 'ready', 'needs_review'].includes(detail.value.status))
const stateLabel = computed(() => selected.value?.state === 'current' ? tr('已确认') : selected.value?.state === 'stale' ? tr('需要复核') : tr('尚未建立'))
const labels: Record<string, string> = { world: '世界观', rule: '故事规则', identity: '人物身份', relation: '人物关系', event: '故事事件', state: '人物与环境状态', outline: '故事大纲', decision: '创作决定' }
const natures: Record<FactNature, string> = { fact: '明确事实', testimony: '人物证言', inference: '尚待证实的推测', plan: '大纲计划', creative_decision: '创作决定' }
const scopeOptions = computed(() => rows.value.map(row => ({
  value: row.chapter_id === null ? 'baseline' : String(row.chapter_id),
  label: row.chapter_id === null ? tr('全局故事底稿') : `${tr('第 {p0} 集', { p0: row.number })} · ${tr(row.state === 'current' ? '已确认' : row.state === 'stale' ? '需要复核' : '尚未建立')}`,
})))
const scopeLabel = computed(() => scopeOptions.value.find(option => option.value === scope.value)?.label)
const natureOptions = computed(() => Object.entries(natures).map(([value, label]) => ({ value, label: tr(label) })))
const worldOptions = computed(() => [{ value: '', label: tr('未指定世界') },
  ...(draft.value?.subjects.filter(subject => subject.kind === 'world').map(world => ({ value: world.ref, label: world.name })) ?? [])])
const commitLabels: Record<MemoryCommit['status'], string> = { pending: '分析中', draft: '尚未审核', ready: '待确认', needs_review: '审核有阻断问题', accepted: '已确认', rejected: '已退回', stale: '已失效' }
function scopeText(value: MemoryScope | Record<string, string | number | null>) {
  const parts: string[] = []
  const worldId = 'world_id' in value ? value.world_id : null
  const world = value.world_ref ? candidate.value?.subjects.find(subject => subject.ref === value.world_ref)?.name
    : context.value?.worlds?.find(world => world.id === worldId)?.name
  if (world) parts.push(tr('世界：{p0}', { p0: world }))
  if (value.scene) parts.push(tr('场景：{p0}', { p0: value.scene }))
  if (value.story_time) parts.push(tr('故事时点：{p0}', { p0: value.story_time }))
  if (value.from_chapter) parts.push(tr('自第 {p0} 集起', { p0: value.from_chapter }))
  if (value.until_chapter) parts.push(tr('至第 {p0} 集', { p0: value.until_chapter }))
  return parts.join(' · ')
}

async function selectCommit(commitId: number) {
  const current = epoch
  const request = ++selection
  const response = await storyMemoryApi.detail(props.projectId, commitId, requests.signal)
  if (current !== epoch || request !== selection) return
  detail.value = response.data
  draft.value = null
  decisionNote.value = ''
}
async function loadScope() {
  const current = epoch
  const view = ++scopeRevision
  ++selection
  const target = chapterId.value
  context.value = null
  detail.value = null
  shownFacts.value = 20
  const latest = commits.value.find(commit => commit.chapter_id === target)?.id ?? selected.value?.commit_id
  const work: Promise<unknown>[] = []
  if (latest) work.push(selectCommit(latest))
  if (selected.value?.state === 'current') work.push(storyMemoryApi.context(props.projectId, target, requests.signal).then(response => {
    if (current === epoch && view === scopeRevision && chapterId.value === target) context.value = response.data
  }))
  await Promise.all(work)
}
async function reload() {
  const current = epoch
  const request = ++refresh
  loading.value = true
  try {
    const [states, records] = await Promise.all([
      storyMemoryApi.status(props.projectId, requests.signal), storyMemoryApi.history(props.projectId, undefined, requests.signal),
    ])
    if (current !== epoch || request !== refresh) return
    status.value = states.data
    commits.value = records.data
    if (!draft.value) await loadScope()
  } catch (reason) {
    if (current === epoch && request === refresh && !requests.signal.aborted) notice.error((reason as Error).message)
  } finally { if (current === epoch && request === refresh) loading.value = false }
}
async function track(taskId: string) {
  const current = epoch
  const poll = ++pollRevision
  clearTimeout(timer)
  try {
    const response = await api.task(taskId, requests.signal)
    if (current !== epoch || poll !== pollRevision) return
    job.value = response.data
    if (requestedRun === taskId && showRunDetails()) requestedRun = undefined
    if (job.value.stage === 'needs_review') {
      await reload()
      if (current !== epoch || poll !== pollRevision || !job.value) return
      const waiting = job.value.response_data?.waiting_commit_id
      if (typeof waiting === 'number') {
        await selectCommit(waiting)
        scope.value = detail.value?.chapter_id ? String(detail.value.chapter_id) : 'baseline'
      }
    } else if ([1, 2, 6].includes(job.value.status)) {
      timer = setTimeout(() => { void track(taskId) }, 1200)
    } else {
      await reload()
    }
  } catch (reason) {
    if (current === epoch && poll === pollRevision && !requests.signal.aborted) notice.error((reason as Error).message)
  }
}
function showRunDetails() {
  const conversationId = job.value?.request_params?.conversation_id
  if (!job.value || typeof conversationId !== 'number') return false
  emit('showRun', { taskId: job.value.id, conversationId })
  return true
}
function showRun() {
  if (showRunDetails()) return
  requestedRun = job.value?.id
  emit('showRun')
}
function openProgress() {
  showRun()
  if (running.value && job.value) void track(job.value.id)
}
function openReview() {
  focusReview.value = true
  emit('showRun')
}
function openMemory() {
  if (!context.value?.enabled || !memoryDialog.value || memoryDialog.value.open) return
  shownFacts.value = 20
  memoryDialog.value.showModal()
  memoryOpen.value = true
}
function focusReviewIssues() {
  document.getElementById(`${id}-review-issues`)?.focus()
}
watch([focusReview, () => props.reviewTarget, hasCandidate], ([focus, target, available]) => {
  if (!focus || !target || !available) return
  target.querySelector<HTMLElement>(`[id="${id}-candidate"]`)?.focus()
  focusReview.value = false
}, { flush: 'post' })
async function action(work: () => Promise<unknown>) {
  if (locked.value || !props.canEdit) return
  const current = epoch
  busy.value = true
  try { await work() } catch (reason) { if (current === epoch) notice.error((reason as Error).message) }
  finally { if (current === epoch) busy.value = false }
}
async function analyze(all = false) {
  if (!modelId.value) { notice.error(tr('请选择故事记忆模型')); return }
  const current = epoch
  await action(async () => {
    const response = all ? await storyMemoryApi.recheck(props.projectId, Number(modelId.value), skillId.value)
      : await storyMemoryApi.analyze(props.projectId, chapterId.value, Number(modelId.value), skillId.value)
    if (current !== epoch) return
    job.value = response.data
    showRun()
    await track(response.data.id)
  })
}
async function decide(decision: 'accept' | 'reject') {
  const current = detail.value
  if (!current) return
  const edition = epoch
  await action(async () => {
    const response = await storyMemoryApi.decide(props.projectId, current.id, current.package_hash, decision, decisionNote.value)
    if (edition !== epoch) return
    detail.value = response.data
    notice.success(decision === 'accept' ? tr('记忆已正式提交') : tr('候选已退回，原有正式记忆仍保留'))
    await reload()
    if (response.data.recheck_task_id) {
      const taskId = response.data.recheck_task_id
      if (decision === 'accept') {
        requestedRun = taskId
        emit('showRun')
      }
      await track(taskId)
    }
    await nextTick()
    document.getElementById(`${id}-${detail.value?.status === 'ready' ? 'candidate' : 'current'}`)?.focus()
  })
}
async function saveDraft() {
  if (!detail.value || !draft.value) return
  const commit = detail.value
  const value = draft.value
  const current = epoch
  const used = new Set(value.facts.flatMap(fact => [fact.subject_ref, fact.scope.world_ref]))
  await action(async () => {
    const facts = value.facts.map(fact => ({ ...fact, scope: { ...fact.scope,
      from_chapter: Number.isFinite(fact.scope.from_chapter) ? fact.scope.from_chapter : null,
      until_chapter: Number.isFinite(fact.scope.until_chapter) ? fact.scope.until_chapter : null } }))
    const response = await storyMemoryApi.update(props.projectId, commit.id, { ...value, facts, subjects: value.subjects.filter(subject => used.has(subject.ref)) }, commit.revision)
    if (current !== epoch) return
    detail.value = response.data
    draft.value = null
    notice.success(tr('候选已保存，请重新审核后再确认'))
  })
}
async function review() {
  if (!detail.value || !modelId.value) { notice.error(tr('请选择故事记忆模型')); return }
  const current = epoch
  await action(async () => {
    const response = await storyMemoryApi.review(props.projectId, detail.value!.id, detail.value!.revision, Number(modelId.value))
    if (current !== epoch) return
    job.value = response.data
    showRun()
    await track(response.data.id)
  })
}
async function repair() {
  const commit = detail.value
  if (!commit?.current || commit.status !== 'needs_review') return
  const current = epoch
  await action(async () => {
    const response = await storyMemoryApi.repair(props.projectId, commit.id, commit.revision, commit.package_hash,
      modelId.value ? Number(modelId.value) : undefined)
    if (current !== epoch) return
    job.value = response.data
    showRun()
    await track(response.data.id)
  })
}
async function editCandidate() {
  if (candidate.value) draft.value = structuredClone(toRaw(candidate.value))
  await nextTick()
  document.getElementById(`${id}-summary`)?.focus()
}
async function cancelEdit() {
  draft.value = null
  await reload()
  await nextTick()
  document.getElementById(`${id}-edit`)?.focus()
}
async function removeFact(index: number) {
  draft.value?.facts.splice(index, 1)
  await nextTick()
  const target = Math.min(index, (draft.value?.facts.length ?? 0) - 1)
  document.getElementById(target >= 0 ? `${id}-fact-${target}` : `${id}-summary`)?.focus()
}
watch(scope, async () => {
  if (memoryDialog.value?.open) memoryDialog.value.close()
  if (!status.value) return
  const current = epoch
  try { await loadScope() }
  catch (reason) { if (current === epoch && !requests.signal.aborted) notice.error((reason as Error).message) }
})
watch(() => props.chapterId, value => {
  if (!draft.value && !busy.value && value) {
    scope.value = String(value)
    if (status.value && !status.value.chapters.some(row => row.chapter_id === value)) void reload()
  }
})
watch(() => props.refreshKey, () => {
  if (!draft.value) void reload()
  else notice.error(tr('剧本已修改，当前候选草稿仍保留；请取消修改后重新分析。'))
})
watch(() => props.canEdit, value => { if (!value) draft.value = null })
watch(() => props.projectId, async () => {
  if (memoryDialog.value?.open) memoryDialog.value.close()
  ++epoch
  const current = epoch
  requests.abort()
  requests = new AbortController()
  clearTimeout(timer)
  requestedRun = undefined
  focusReview.value = false
  job.value = null
  busy.value = false
  draft.value = null
  status.value = null
  commits.value = []
  detail.value = null
  context.value = null
  scope.value = props.chapterId ? String(props.chapterId) : 'baseline'
  await reload()
  if (current !== epoch || requests.signal.aborted) return
  try {
    const response = await storyMemoryApi.activity(props.projectId, requests.signal)
    if (current === epoch && response.data) await track(response.data.id)
  } catch (reason) { if (current === epoch && !requests.signal.aborted) notice.error((reason as Error).message) }
}, { immediate: true })
onBeforeUnmount(() => { ++epoch; requests.abort(); clearTimeout(timer) })
</script>

<template>
  <section class="story-memory" :aria-labelledby="`${id}-heading`">
    <header class="memory-header">
      <div><h2 :id="`${id}-heading`"><BookOpen :size="18" aria-hidden="true" />{{ tr('故事记忆') }}</h2><p>{{ tr('已确认的世界观、人物和前情，将用于资产、分镜与创作助手。') }}</p></div>
      <div class="memory-actions">
        <AppBadge :tone="selected?.state === 'current' ? 'success' : selected?.state === 'stale' ? 'warning' : 'neutral'">{{ stateLabel }}</AppBadge>
        <AppButton v-if="selected?.state === 'current'" :id="`${id}-current`" size="sm" variant="soft"
          aria-haspopup="dialog" :aria-controls="`${id}-memory-dialog`" :disabled="!context?.enabled" @click="openMemory">{{ tr('查看当前有效记忆') }}</AppButton>
        <AppButton v-if="hasCandidate" size="sm" variant="soft" :aria-controls="reviewTarget ? `${id}-candidate-panel` : undefined" @click="openReview">{{ tr('在创作助手查看候选') }}</AppButton>
        <AppButton v-if="canEdit && (running || (!hasCandidate && job?.stage === 'needs_review') || job?.status === 4)" size="sm" variant="ghost" @click="openProgress">{{ tr('在创作助手查看进度') }}</AppButton>
        <AppButton size="sm" :disabled="loading || Boolean(draft)" @click="reload"><RefreshCw :size="14" aria-hidden="true" />{{ tr('刷新记忆') }}</AppButton>
      </div>
    </header>
    <div v-if="loading && !status" class="memory-skeleton" :aria-label="tr('正在读取故事记忆')" aria-busy="true"><span></span><span></span></div>
    <template v-if="status">
      <div class="memory-controls">
        <div class="memory-field"><label :id="`${id}-scope-label`">{{ tr('查看范围') }}</label><AppSelect v-model="scope" :aria-labelledby="`${id}-scope-label`" :ariaLabel="tr('查看范围')" density="compact" :options="scopeOptions" :disabled="Boolean(draft) || busy" /></div>
        <template v-if="canEdit">
          <div class="memory-field"><label :id="`${id}-model-label`">{{ tr('故事记忆模型') }}</label><AppSelect v-model="modelId" :aria-labelledby="`${id}-model-label`" :ariaLabel="tr('故事记忆模型')" density="compact" :options="[{ value: '', label: tr(modelsLoading ? '正在读取模型…' : models.length ? '选择分析模型' : '暂无可用模型') }, ...models]" :disabled="locked || !models.length || modelsLoading" /></div>
          <TaskSkillPicker v-model="skillId" task="story" :disabled="locked" />
          <div class="memory-actions"><AppButton size="sm" variant="soft" :disabled="locked || Boolean(draft) || !selected?.can_analyze" @click="analyze(false)">{{ tr('分析当前范围') }}</AppButton><AppButton size="sm" variant="primary" :disabled="locked || Boolean(draft)" @click="analyze(true)">{{ tr('顺序复核全部') }}</AppButton></div>
        </template>
      </div>
      <p v-if="canEdit && !modelsLoading && !models.length" class="memory-hint">{{ tr('暂无可用的故事记忆模型，请在设置中配置或联系管理员。') }}</p>
      <p v-if="status.baseline.state === 'missing'" class="memory-hint">{{ tr('先建立全局故事底稿，再逐章确认。建立前，生成仍使用项目设定和当前剧本。') }}</p>
      <p v-else-if="selected?.state !== 'current'" class="memory-hint">{{ selected?.blocked_by || selected?.reason }} · {{ tr('复核确认后，才能使用这一范围的记忆生成。') }}</p>
    </template>
  </section>
  <Teleport to="body">
    <dialog ref="memoryDialog" :id="`${id}-memory-dialog`" :aria-labelledby="`${id}-memory-dialog-title`"
      class="memory-dialog" @close="memoryOpen = false">
      <header class="memory-dialog-header">
        <div>
          <h2 :id="`${id}-memory-dialog-title`">{{ tr('当前有效记忆') }}</h2>
          <p v-if="scopeLabel" class="memory-dialog-scope">{{ scopeLabel }}</p>
        </div>
        <form method="dialog">
          <AppButton type="submit" size="sm" icon-only variant="ghost" :aria-label="tr('关闭')" autofocus><X :size="18" aria-hidden="true" /></AppButton>
        </form>
      </header>
      <div v-if="memoryOpen && context?.enabled" class="memory-dialog-body">
        <p class="memory-prose">{{ context.current?.summary }}</p>
        <p v-if="chapterId && context.baseline_summary" class="memory-hint">{{ tr('全局背景') }}：{{ context.baseline_summary }}</p>
        <p v-if="context.previous?.ending_state" class="memory-hint">{{ tr('前章状态') }}：{{ context.previous.ending_state }}</p>
        <details v-if="context.facts?.length"><summary>{{ tr('查看已确认事实（{p0}）', { p0: context.facts.length }) }}</summary>
        <ul class="memory-facts" role="list"><li v-for="fact in context.facts.slice(0, shownFacts)" :key="fact.id"><div class="fact-heading"><strong>{{ fact.subject.name }}</strong><span>{{ tr(labels[fact.category] || fact.category) }} · {{ tr(natures[fact.nature]) }}</span></div><p>{{ fact.content }}</p><p v-if="scopeText(fact.scope)" class="memory-hint">{{ scopeText(fact.scope) }}</p><details><summary>{{ tr('原文依据') }}</summary><blockquote v-for="(evidence, index) in fact.evidence" :key="index">{{ evidence.quote }}</blockquote></details></li></ul>
        <AppButton v-if="(context.facts?.length || 0) > shownFacts" size="sm" @click="shownFacts += 20">{{ tr('显示更多事实') }}</AppButton>
        </details>
      </div>
      <p v-else-if="memoryOpen" class="memory-dialog-body memory-hint" role="status">{{ tr(loading ? '正在读取故事记忆' : '当前范围暂无可查看的有效记忆') }}</p>
    </dialog>
  </Teleport>
  <Teleport v-if="reviewTarget && hasCandidate && detail && candidate" :to="reviewTarget">
      <section :id="`${id}-candidate-panel`" class="memory-candidate" :aria-labelledby="`${id}-candidate`">
        <div class="memory-section-heading"><h3 :id="`${id}-candidate`" tabindex="-1">{{ tr('候选与审核') }}</h3><AppBadge :tone="detail.status === 'ready' ? 'accent' : detail.status === 'needs_review' || detail.status === 'stale' ? 'warning' : 'neutral'">{{ tr(commitLabels[detail.status]) }}</AppBadge></div>
        <p class="memory-hint">{{ scopeOptions.find(option => option.value === (detail?.chapter_id ? String(detail.chapter_id) : 'baseline'))?.label }}</p>
        <p v-if="detail.source_snapshot?.opening_chapter" class="memory-hint">{{ tr('开篇依据：第 {p0} 集 · {p1}', { p0: detail.source_snapshot.opening_chapter.number, p1: detail.source_snapshot.opening_chapter.name }) }}</p>
        <p v-if="!detail.current" class="memory-hint">{{ detail.stale_reason }}</p>
        <p v-if="detail.review.summary" class="memory-prose">{{ detail.review.summary }}</p>
        <ul v-if="detail.review.issues?.length" :id="`${id}-review-issues`" tabindex="-1" :aria-label="tr('审核意见')" class="review-issues"><li v-for="(issue, index) in detail.review.issues" :key="index"><strong>{{ tr(issue.severity === 'blocking' ? '需处理' : '请留意') }}</strong> · {{ issue.reason }}</li></ul>
        <form v-if="draft" class="memory-editor" :aria-labelledby="`${id}-edit-heading`" @submit.prevent="saveDraft">
          <h4 :id="`${id}-edit-heading`">{{ tr('修改候选记忆') }}</h4>
          <div class="memory-field"><label :for="`${id}-summary`">{{ tr('故事摘要') }}</label><textarea :id="`${id}-summary`" v-model="draft.summary" name="summary" required maxlength="8000" rows="3" :disabled="locked"></textarea></div>
          <div class="memory-field"><label :for="`${id}-ending`">{{ tr('章末状态') }}</label><textarea :id="`${id}-ending`" v-model="draft.ending_state" name="ending_state" maxlength="8000" rows="2" :disabled="locked"></textarea></div>
          <fieldset v-for="(fact, index) in draft.facts" :key="index" :disabled="locked">
            <legend>{{ draft.subjects.find(subject => subject.ref === fact.subject_ref)?.name }} · {{ tr(labels[fact.category] || fact.category) }}</legend>
            <div class="memory-field"><label :for="`${id}-fact-${index}`">{{ tr('事实描述') }}</label><textarea :id="`${id}-fact-${index}`" v-model="fact.content" :name="`fact_${index}`" required maxlength="8000" rows="3"></textarea></div>
            <div class="memory-field"><label :id="`${id}-nature-${index}-label`">{{ tr('记忆性质') }}</label><AppSelect :model-value="fact.nature" :aria-labelledby="`${id}-nature-${index}-label`" :ariaLabel="tr('记忆性质')" density="compact" :options="natureOptions" :disabled="locked" @update:model-value="fact.nature = $event as FactNature" /></div>
            <details><summary>{{ tr('调整适用范围') }}</summary>
              <div class="memory-scope-fields">
                <div class="memory-field"><label :id="`${id}-world-${index}-label`">{{ tr('所属世界') }}</label><AppSelect :model-value="fact.scope.world_ref ?? ''" :aria-labelledby="`${id}-world-${index}-label`" :ariaLabel="tr('所属世界')" density="compact" :options="worldOptions" :disabled="locked" @update:model-value="fact.scope.world_ref = $event || null" /></div>
                <div class="memory-field"><label :for="`${id}-scene-${index}`">{{ tr('适用场景（可选）') }}</label><input :id="`${id}-scene-${index}`" v-model="fact.scope.scene" :name="`scene_${index}`" maxlength="8000" /></div>
                <div class="memory-field"><label :for="`${id}-time-${index}`">{{ tr('故事时点（可选）') }}</label><input :id="`${id}-time-${index}`" v-model="fact.scope.story_time" :name="`time_${index}`" maxlength="8000" /></div>
                <div class="memory-field"><label :for="`${id}-from-${index}`">{{ tr('起始集号（可选）') }}</label><input :id="`${id}-from-${index}`" v-model.number="fact.scope.from_chapter" :name="`from_${index}`" type="number" min="1" step="1" /></div>
                <div class="memory-field"><label :for="`${id}-until-${index}`">{{ tr('结束集号（可选）') }}</label><input :id="`${id}-until-${index}`" v-model.number="fact.scope.until_chapter" :name="`until_${index}`" type="number" :min="fact.scope.from_chapter || 1" step="1" /></div>
              </div>
            </details>
            <details><summary>{{ tr('原文依据') }}</summary><blockquote v-for="(evidence, item) in fact.evidence" :key="item">{{ evidence.quote }}</blockquote></details>
            <AppButton size="xs" :disabled="busy" @click="removeFact(index)">{{ tr('移除此条候选') }}</AppButton>
          </fieldset>
          <p class="memory-hint">{{ tr('修改后需要重新审核；原文证据和旧正式提交会保留。') }}</p>
          <div class="memory-actions"><AppButton type="submit" variant="primary" size="sm" :loading="busy" :disabled="props.disabled || Boolean(running)">{{ tr('保存候选') }}</AppButton><AppButton size="sm" :disabled="busy" @click="cancelEdit">{{ tr('取消修改') }}</AppButton></div>
        </form>
        <template v-else>
          <p class="memory-prose">{{ candidate.summary }}</p><p v-if="candidate.ending_state" class="memory-hint">{{ tr('章末状态') }}：{{ candidate.ending_state }}</p>
          <ul class="memory-facts" role="list"><li v-for="(fact, index) in candidate.facts" :key="index"><div class="fact-heading"><strong>{{ candidate.subjects.find(subject => subject.ref === fact.subject_ref)?.name }}</strong><span>{{ tr(labels[fact.category] || fact.category) }} · {{ tr(natures[fact.nature]) }}</span></div><p>{{ fact.content }}</p><p v-if="scopeText(fact.scope)" class="memory-hint">{{ scopeText(fact.scope) }}</p><p v-if="fact.replaces_id" class="memory-hint">{{ tr(fact.operation === 'retract' ? '将撤回' : '将替代') }}：{{ detail.replaced_facts?.[fact.replaces_id] || tr('原有同类事实') }}</p><details><summary>{{ tr('原文依据') }}</summary><blockquote v-for="(evidence, item) in fact.evidence" :key="item">{{ evidence.quote }}</blockquote></details></li></ul>
          <p v-if="candidate.unresolved.length" class="memory-hint">{{ tr('尚未明确') }}：{{ candidate.unresolved.join('；') }}</p>
          <template v-if="editable && detail.status === 'needs_review'">
            <p class="memory-hint">{{ tr('助手会按审核意见和原文补全候选，并重新审核。退回则结束本轮。') }}</p>
            <div class="memory-actions">
              <AppButton size="sm" variant="primary" :disabled="locked" @click="repair">{{ tr('按审核意见补全') }}</AppButton>
              <AppButton size="sm" :disabled="locked" @click="decide('reject')">{{ tr('退回候选') }}</AppButton>
              <AppButton v-if="detail.review.issues?.length" size="xs" variant="ghost" @click="focusReviewIssues">{{ tr('查看审核意见') }}</AppButton>
            </div>
          </template>
          <template v-else-if="emptyBaseline">
            <p v-if="detail.status === 'ready'" class="memory-hint">{{ tr('全局故事底稿没有可确认事实，请补充故事材料后重新分析') }}</p>
            <AppButton v-if="editable" size="sm" :disabled="locked" @click="decide('reject')">{{ tr('退回候选') }}</AppButton>
          </template>
          <template v-else-if="editable">
            <div class="memory-field"><label :for="`${id}-note`">{{ tr('核对说明（可选）') }}</label><textarea :id="`${id}-note`" v-model="decisionNote" name="decision_note" maxlength="4000" rows="2" :disabled="locked"></textarea></div>
            <div v-if="detail.status !== 'ready'" class="memory-actions">
              <p :id="`${id}-confirm-hint`" class="memory-hint">{{ tr('候选尚未审核，请先重新审核。') }}</p>
            </div>
            <div class="memory-actions">
              <AppButton :id="`${id}-edit`" size="sm" :disabled="locked" @click="editCandidate">{{ tr('修改候选') }}</AppButton>
              <AppButton size="sm" variant="soft" :disabled="locked" @click="review">{{ tr('重新审核') }}</AppButton>
              <AppButton size="sm" :disabled="locked" @click="decide('reject')">{{ tr('退回候选') }}</AppButton>
              <AppButton size="sm" variant="primary" :disabled="locked || detail.status !== 'ready'"
                :aria-describedby="detail.status !== 'ready' ? `${id}-confirm-hint` : undefined"
                @click="decide('accept')">{{ tr('确认并入库') }}</AppButton>
            </div>
          </template>
        </template>
      </section>
  </Teleport>
</template>

<style scoped>
.story-memory { min-width: 0; padding: 24px; margin-block: 28px; border: 1px solid var(--app-border); border-radius: 16px; color: var(--app-text); background: var(--app-surface); }
.memory-header, .memory-section-heading, .memory-actions, .fact-heading { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.memory-header { justify-content: space-between; align-items: flex-start; gap: 16px; }
.memory-header h2 { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 18px; }
.memory-header p { margin: 8px 0 0; color: var(--app-text-secondary); font-size: 13px; line-height: 1.7; }
.memory-controls { display: flex; align-items: flex-end; flex-wrap: wrap; gap: 14px; margin-block: 22px 12px; }
.memory-controls > .memory-field { flex: 0 1 210px; }
.memory-controls :deep(.task-skill-picker) { width: auto; max-width: 100%; flex: 0 1 auto; margin-block: 10px; }
.memory-controls > .memory-actions { margin-inline-start: auto; margin-block: 10px; }
.memory-field { display: grid; gap: 6px; min-width: 0; margin-block: 10px; }
.memory-field label, legend { color: var(--app-text-secondary); font-size: 12px; font-weight: 600; }
.memory-field :deep(.app-select) { width: 100%; }
textarea, input { width: 100%; box-sizing: border-box; min-height: 38px; padding: 9px 11px; border: 1px solid var(--app-border); border-radius: 8px; color: var(--app-text); background: var(--app-surface-muted); font: inherit; font-size: 14px; line-height: 1.6; caret-color: var(--app-accent); }
textarea { resize: vertical; }
textarea:focus-visible, input:focus-visible, summary:focus-visible { outline: 2px solid var(--app-accent); outline-offset: 3px; }
textarea::placeholder { color: var(--app-text-muted); }
textarea:disabled, input:disabled { opacity: .55; cursor: not-allowed; }
.memory-scope-fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(210px, 100%), 1fr)); gap: 12px; }
.memory-hint { margin-block: 10px; color: var(--app-text-secondary); font-size: 13px; line-height: 1.7; overflow-wrap: anywhere; }
.memory-dialog { box-sizing: border-box; inline-size: min(720px, calc(100% - 24px)); max-block-size: calc(100dvh - 32px); margin: auto; padding: 0; overflow: auto; border: 1px solid var(--app-border); border-radius: 16px; background: var(--app-surface); color: var(--app-text); }
.memory-dialog:modal { overscroll-behavior: contain; }
.memory-dialog::backdrop { background: rgb(0 0 0 / 55%); overflow: hidden; overscroll-behavior: contain; }
.memory-dialog-header { position: sticky; inset-block-start: 0; z-index: 1; display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 16px 20px; background: var(--app-surface); border-block-end: 1px solid var(--app-border); }
.memory-dialog-header h2 { margin: 0; font-size: 18px; }
.memory-dialog-scope { margin: 5px 0 0; color: var(--app-text-secondary); font-size: 12px; overflow-wrap: anywhere; }
.memory-dialog-body { padding: 4px 20px 18px; }
.memory-candidate { min-inline-size: 0; color: var(--app-text); }
.memory-candidate .memory-field :deep(.app-select) { min-inline-size: 0; }
h3 { margin: 0 0 10px; font-size: 15px; }
h4 { margin-block: 0 16px; font-size: 14px; }
.memory-section-heading h3 { margin: 0; }
.memory-prose { max-width: 75ch; white-space: pre-wrap; overflow-wrap: anywhere; margin-block: 14px; line-height: 1.8; font-size: 14px; }
.memory-facts { padding: 0; margin: 12px 0; list-style: none; }
.memory-facts > li { padding-block: 14px; border-block-end: 1px solid var(--app-border); }
.memory-facts > li:last-child { border: 0; }
.fact-heading strong { font-size: 13px; }
.fact-heading span { color: var(--app-text-secondary); font-size: 12px; }
.memory-facts p { max-width: 75ch; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 14px; line-height: 1.8; margin-block: 8px; }
summary { padding-block: 8px; min-height: 24px; box-sizing: border-box; color: var(--app-text-secondary); cursor: pointer; font-size: 12px; }
summary:hover { color: var(--app-accent); }
blockquote { margin: 8px 0; padding: 12px 16px; border-inline-start: 1px solid var(--app-border); background: var(--app-surface-muted); color: var(--app-text-secondary); white-space: pre-wrap; overflow-wrap: anywhere; font-size: 13px; line-height: 1.8; }
fieldset { min-width: 0; border: 0; padding: 16px 0; margin: 16px 0; border-block-start: 1px solid var(--app-border); }
.review-issues { padding-inline-start: 20px; color: var(--app-text-secondary); font-size: 13px; line-height: 1.8; }
.review-issues:focus-visible { outline: 2px solid var(--app-accent); outline-offset: 3px; }
.memory-skeleton { display: grid; gap: 10px; padding-block: 24px; }
.memory-skeleton span { height: 20px; width: 75%; border-radius: 5px; background: var(--app-surface-muted); }
.memory-skeleton span:last-child { width: 45%; }
@media (max-width: 680px) { .story-memory { padding: 18px 14px; } .memory-controls > .memory-field { flex-basis: 100%; } .memory-controls > .memory-actions { margin-inline-start: 0; } .memory-controls > .memory-actions :deep(button) { white-space: normal; } }
@media (pointer: coarse) { textarea, input { font-size: 16px; min-height: 48px; } summary { min-height: 48px; padding-block: 12px; } :is(.story-memory, .memory-candidate, .memory-dialog) :deep(.app-button) { min-height: 48px; } }
</style>
