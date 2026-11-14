<script setup lang="ts">
import AgentRecoveryDetails from './AgentRecoveryDetails.vue'
import AgentPlanDetails from './AgentPlanDetails.vue'
import { tr } from '@/i18n'
import AppSelect from '@/components/AppSelect.vue'

import AgentUsageDetails from './AgentUsageDetails.vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { BubbleList } from 'vue-element-plus-x'
import type { BubbleListInstance } from 'vue-element-plus-x/types/BubbleList'
import { Bot, RefreshCw, X, BookOpenText, ChevronsUpDown } from 'lucide-vue-next'
import { api } from '@/api'
import type { VideoGenerationOptions } from '@/types'
import AppButton from '@/components/AppButton.vue'
import { notice } from '@/shared/notice'
import { useCreationAgentStore } from './store'
import { agentApi } from './api'
import PromptChangeCard from './PromptChangeCard.vue'
import AgentQueryResults from './AgentQueryResults.vue'
import AgentComposer from './AgentComposer.vue'
import AgentConversationMenu from './AgentConversationMenu.vue'
import AgentTargetPicker from './AgentTargetPicker.vue'
import AgentSetupState from './AgentSetupState.vue'
import AgentDisclosure from './AgentDisclosure.vue'
import AgentActivity from './AgentActivity.vue'
import AgentRunActivity from './AgentRunActivity.vue'
import { targetKey, useCreationAgentWorkspace, type AgentTargetOption } from './workspace'
import type { AgentChange, AgentChangeItem, AgentQueryItem, AgentTarget, ProductionReceipt, PromptTargetStatus } from './types'

const props = defineProps<{ projectId: number; chapterId: number; selectedTargets?: AgentTarget[]; workflow?: boolean; chapterLabel?: string; suspended?: boolean; phase?: 'script' | 'settings' | 'storyboard' | 'video'; initialConversationId?: number; initialUserText?: string; videoDefaults?: VideoGenerationOptions & { model_config_id: number } }>()
const emit = defineEmits<{ close: []; changed: [changes: AgentChange[]] }>()
const store = useCreationAgentStore()
const router = useRouter()
const workspace = useCreationAgentWorkspace()
workspace.enterProject(props.projectId)
const composer = ref<InstanceType<typeof AgentComposer> | null>(null)
const messageList = ref<BubbleListInstance | null>(null)
const modelId = computed({ get: () => workspace.modelId, set: value => { workspace.modelId = value } })
const draftKey = computed(() => store.conversationId ? `conversation:${store.conversationId}` : 'new')
const draft = computed({ get: () => workspace.drafts[draftKey.value] ?? '', set: value => { workspace.drafts[draftKey.value] = value } })
const selected = computed({
  get: () => workspace.selection.map(option => targetKey(option.target)),
  set: keys => workspace.select(keys.flatMap(key => {
    const option = allOptions.value.find(item => item.key === key)
    return option ? [option] : []
  })),
})
const options = ref<(AgentTargetOption & { key: string })[]>([])
const pickerOpen = ref(false)
const writeScope = ref<'chapter' | 'project' | 'read_only'>('chapter')

const effectiveWriteScope = computed(() => !props.chapterId && writeScope.value === 'chapter' ? 'project' : writeScope.value)

function changeWriteScope(next: string) {
  if (next === writeScope.value) return
  writeScope.value = next as typeof writeScope.value
  if (next !== 'read_only') workspace.select([])
}
const catalogLoading = ref(false)
const catalogPage = ref(1)
const hasMoreAssets = ref(false)
const hasMoreScenes = ref(false)
const operationBusy = ref(false)
const pendingConstraints = ref<Record<string, PromptTargetStatus['pending_constraints']>>({})
const statusError = ref('')
const messageExpansion = ref<Record<number, boolean>>({})
const statusOpen = ref(false)
const pendingCount = computed(() => allOptions.value.filter(option => pendingConstraints.value[option.key]?.length).length)
let catalogEpoch = 0
let statusEpoch = 0
const writable = computed(() => store.capabilities?.enabled && store.capabilities.can_write)
const ready = computed(() => writable.value && Boolean(store.capabilities?.models.length))
const failedRequest = computed(() => store.currentRun?.status === 4
  ? store.messages.find(message => message.role === 'user' && message.task_id === store.currentRun?.task_id)?.content : undefined)
const targets = computed(() => workspace.selection.map(option => option.target))
const allOptions = computed(() => [...new Map([
  ...workspace.selection.map(option => ({ ...option, key: targetKey(option.target) })), ...options.value,
].map(option => [option.key, option])).values()])
const suggestions = computed(() => targets.value.length ? [
  tr('光线更柔和，保留人物外貌和服装。'),
  tr('画面更有电影感，每个分镜独立完整描述。'),
] : [tr('先聊聊这个故事适合怎样的画面风格。'), tr('帮我梳理人物与场景需要保持一致的设定。')])
const welcomeHint = computed(() => targets.value.length ? tr('已指定操作对象，直接说出你希望的变化。')
  : tr('可以查找设定、新增分镜或调整画面。直接描述要求，助手会在当前范围内找到对象。'))

function applyDefaults() {
  if (workspace.scopeEdited || store.busy) return
  workspace.select((props.selectedTargets ?? []).map(target => options.value.find(option => option.key === targetKey(target))
    ?? { target, label: target.kind === 'scene' ? tr('当前分镜') : tr('当前图片设定') }), false)
}

function selectSuggestion(text: string) { draft.value = text; void nextTick(() => composer.value?.focus()) }
function removeTarget(option: AgentTargetOption) {
  if (!store.busy) workspace.select(workspace.selection.filter(item => targetKey(item.target) !== targetKey(option.target)))
}
const productionLabel = (operation: string) => tr(({ story: '项目分析', assets: '资产提取', image: '图片生成', storyboard: '分镜生成', storyboard_sheet: '生成线稿故事版', video: '视频生成', remake: '视频重制', compose: '章节合成', prepare_export: '准备当前原片', enhance_export: '增强到1080p' } as Record<string, string>)[operation] || operation)
function singleProductionResult(message: { role: string; content: string; production?: ProductionReceipt[] }): ProductionReceipt | undefined {
  const receipt = message.production?.length === 1 ? message.production[0] : undefined
  return message.role === 'assistant' && ['', '已完成', 'Completed', '任务未完成', 'Task failed', '后续步骤已停止', 'Further steps stopped', '处理中', 'Processing'].includes(message.content.trim()) ? receipt : undefined
}
const bubbles = computed(() => store.messages.map(message => props.initialUserText && store.conversationId === props.initialConversationId
  && message.id === store.messages.find(item => item.role === 'user')?.id ? { ...message, content: props.initialUserText } : message).filter(message => message.role === 'user' ||
  message.content || message.query_results?.length || message.changes.length || message.activity?.length || message.production?.length || message.started_at || [1, 2, 4, 5, 6].includes(message.status),
).map(message => ({ ...message,
  activityStatus: message.production?.some(receipt => [1, 2, 6].includes(receipt.status)) ? 2 : message.status,
  singleProductionResult: singleProductionResult(message),
  paragraphs: singleProductionResult(message) ? [] : message.content.split(/\n\s*\n/).filter(Boolean),
  noStyle: message.role === 'assistant',
  preview: message.content.replace(/\s+/g, ' ').slice(0, 90) || (message.changes.length ? tr('{p0} 条修改记录', { p0: message.changes.length }) : message.status === 4 ? tr('本轮未完成') : tr('查询与处理记录')),
  placement: message.role === 'user' ? 'end' as const : 'start' as const,
  variant: message.role === 'user' ? 'filled' as const : 'borderless' as const,
  maxWidth: '100%', loading: false,
})))
const messageIsOpen = (message: { id: number; role: string }) => messageExpansion.value[message.id] ?? message.role === 'assistant'
const allCollapsed = computed(() => bubbles.value.length > 0 && bubbles.value.every(message => !messageIsOpen(message)))
function toggleMessage(id: number, open: boolean) {
  messageExpansion.value[id] = open
}
function toggleAllMessages() {
  const open = allCollapsed.value
  messageExpansion.value = Object.fromEntries(bubbles.value.map(message => [message.id, open]))
}
const currentProductionActive = computed(() => bubbles.value.some(message => message.task_id === store.currentRun?.task_id && message.status === 3 && message.activityStatus === 2))
const statusLabel = computed(() => store.error ? store.busy ? tr('连接中断 · 正在恢复状态') : tr('本轮未完成 · 查看原因') : currentProductionActive.value ? tr('处理中') : store.statusText || tr('创作上下文'))
watch(() => store.error, error => { if (error) statusOpen.value = true })
watch(() => store.conversationId, () => { messageExpansion.value = {}; statusOpen.value = false })

async function loadTargets(more = false) {
  const epoch = ++catalogEpoch
  if (!more) { statusEpoch += 1; pendingConstraints.value = {}; statusError.value = ''; options.value = [] }
  catalogLoading.value = true
  const page = more ? catalogPage.value + 1 : 1
  try {
    const [assets, scenes] = await Promise.all([
      !more || hasMoreAssets.value ? api.assets(props.projectId, page, 50, props.chapterId || undefined) : Promise.resolve(null),
      props.chapterId && (!more || hasMoreScenes.value) ? api.scenes(props.chapterId, page) : Promise.resolve(null),
    ])
    if (epoch !== catalogEpoch) return
    const assetOptions = (assets?.data.items ?? []).flatMap(asset => [
      { key: `asset:${asset.id}`, target: { kind: 'asset' as const, id: asset.id }, label: asset.canonical_name, assetType: asset.asset_type },
      ...(asset.variants ?? []).map(variant => ({ key: `variant:${variant.id}`, target: { kind: 'variant' as const, id: variant.id }, label: `${asset.canonical_name} · ${variant.name}`, assetType: asset.asset_type })),
    ])
    const addedOptions = [
      ...(scenes?.data.items ?? []).map(scene => ({ key: `scene:${scene.id}`, target: { kind: 'scene' as const, id: scene.id }, label: tr('镜头 {p0} · {p1}', { p0: scene.sequence, p1: scene.description || tr('未命名') }) })), ...assetOptions,
    ]
    options.value = more ? [...options.value, ...addedOptions] : addedOptions
    catalogPage.value = page
    hasMoreAssets.value = page < (assets?.data.pagination.pages ?? 0)
    hasMoreScenes.value = page < (scenes?.data.pagination.pages ?? 0)
    if (!more) applyDefaults()
    await refreshTargetStatus()
  } catch (error) { notice.error(error instanceof Error ? error.message : tr('无法加载当前对象')) }
  finally { if (epoch === catalogEpoch) catalogLoading.value = false }
}

async function refreshTargetStatus() {
  const epoch = ++statusEpoch
  const projectId = props.projectId
  const chapterId = props.chapterId
  const currentTargets = allOptions.value.map(option => option.target)
  if (!currentTargets.length) { pendingConstraints.value = {}; return }
  const batches = []
  for (let index = 0; index < currentTargets.length; index += 100) batches.push(currentTargets.slice(index, index + 100))
  try {
    const responses = await Promise.all(batches.map(batch => agentApi.promptStatus(projectId, chapterId, batch)))
    if (epoch !== statusEpoch) return
    pendingConstraints.value = Object.fromEntries(responses.flatMap(response => response.data).map(status => [`${status.kind}:${status.id}`, status.pending_constraints]))
    statusError.value = ''
  } catch {
    if (epoch === statusEpoch) statusError.value = tr('暂时无法检查新约束，请稍后重新打开对象列表。')
  }
}

watch(() => [props.projectId, props.initialConversationId] as const, async ([id, conversationId]) => {
  workspace.enterProject(id)
  await store.open(id)
  if (props.projectId === id && props.initialConversationId === conversationId && conversationId && store.conversationId !== conversationId) {
    await store.selectConversation(conversationId)
  }
}, { immediate: true })
watch(() => [props.projectId, props.chapterId], () => {
  workspace.enterChapter(props.chapterId)
  void loadTargets()
}, { immediate: true })
watch(() => store.capabilities?.models, models => {
  if (!models?.some(model => String(model.id) === modelId.value)) modelId.value = String(models?.[0]?.id ?? '')
})
watch(() => (props.selectedTargets ?? []).map(targetKey).join('|'), applyDefaults)
watch(() => [ready.value, store.loading], () => {
  if (ready.value && !store.loading) void nextTick(() => { messageList.value?.scrollToBottom(false) })
})
watch(() => workspace.focusRevision, () => { pickerOpen.value = false; void refreshTargetStatus(); void nextTick(() => composer.value?.focus()) })
watch(() => store.conversationId, (id, previous) => {
  if (id && !previous && store.submitting && workspace.drafts.new) {
    workspace.drafts[`conversation:${id}`] = workspace.drafts.new
    workspace.drafts.new = ''
  }
})
watch(() => store.changesRevision, () => {
  const removed = new Set(store.latestChanges.flatMap(change => change.changes.filter(item =>
    change.reverted_at ? item.operation === 'create' : item.operation === 'delete').map(item => `${item.kind}:${item.target_id}`)))
  if (removed.size) workspace.select(workspace.selection.filter(option => !removed.has(targetKey(option.target))))
  emit('changed', store.latestChanges)
  void loadTargets()
})
watch(() => [store.busy, store.changesRevision], () => { if (!store.busy) void refreshTargetStatus() })
watch(pickerOpen, open => { if (open) void refreshTargetStatus() })

async function send(text: string) {
  if (!text.trim() || !ready.value || store.busy || props.suspended) return
  const key = draftKey.value
  if (await store.send({ message: text.trim(), chapter_id: props.chapterId || null, model_config_id: Number(modelId.value) || null,
    targets: targets.value, write_scope: writeScope.value === 'read_only' ? 'read_only' : targets.value.length ? 'selected' : effectiveWriteScope.value })) {
    workspace.drafts[key] = ''
    // The first accepted request creates a conversation with its own draft slot.
    workspace.drafts[draftKey.value] = ''
    await nextTick()
    messageList.value?.scrollToBottom(false)
  }
}

async function confirmProduction(pending: import('./types').PendingProduction) {
  if (props.suspended) return
  if (pending.plan_confirmation) {
    await store.send({ request_id: pending.confirmation_request_id, message: pending.message,
      chapter_id: pending.chapter_id, targets: [], write_scope: pending.write_scope,
      model_config_id: pending.model_config_id, plan_confirmation: pending.plan_confirmation })
    return
  }
  const productionIntents = pending.intents.map(intent => {
    if (intent.operation !== 'video' || !props.videoDefaults ||
      (intent.media_model_config_id && intent.media_model_config_id !== props.videoDefaults.model_config_id)) return intent
    const { model_config_id, ...options } = props.videoDefaults
    const overrides = Object.fromEntries(Object.entries(intent.video_options ?? {}).filter(([key, value]) =>
      value != null && !(key === 'reference_media' && Array.isArray(value) && !value.length)))
    return { ...intent, media_model_config_id: model_config_id, video_options: { ...options, ...overrides } }
  })
  await store.send({ request_id: pending.confirmation_request_id, message: pending.message,
    chapter_id: pending.chapter_id, targets: pending.targets, write_scope: pending.write_scope,
    model_config_id: pending.model_config_id, production_intents: productionIntents })
}

async function operation(action: () => Promise<unknown>) {
  operationBusy.value = true
  try { await action() } catch (error) { notice.error(error instanceof Error ? error.message : tr('操作失败')) }
  finally { operationBusy.value = false }
}

async function newConversation() {
  await operation(async () => {
    await store.newConversation()
    await nextTick()
    composer.value?.focus()
  })
}

function editFailedRequest() {
  if (failedRequest.value) selectSuggestion(failedRequest.value)
}

function close() {
  emit('close')
}

async function locate(target: AgentChangeItem) {
  if (target.kind === 'chapter') {
    await router.push({path: `/create/short-drama/agent/${props.projectId}`, query: {chapter: target.target_id}})
  } else if (target.kind === 'scene') {
    const scene = (await api.scene(target.target_id)).data
    await router.push({ path: `/create/short-drama/storyboard/${props.projectId}`, query: { chapter: scene.chapter_id, scene: scene.id } })
  } else {
    const assetId = target.kind === 'variant' ? target.asset_id : target.target_id
    if (!assetId) throw new Error(tr('这条历史记录缺少所属资产信息，请从设定页选择对应形象。'))
    await router.push({ path: `/create/short-drama/manual/${props.projectId}`, query: { chapter: props.chapterId || undefined, asset: assetId, variant: target.kind === 'variant' ? target.target_id : undefined } })
  }
}

async function locateQuery(target: AgentQueryItem) {
  if (target.kind === 'chapter') {
    await router.push({ path: `/create/short-drama/storyboard/${props.projectId}`, query: { chapter: target.id } })
    return
  }
  await locate({ kind: target.kind, target_id: target.id, asset_id: target.asset_id, chapter_id: target.chapter_id,
    target_label: target.name, before: {}, after: {}, after_version: '' })
}

function selectQueryTarget(target: AgentQueryItem) {
  if (target.kind === 'chapter' || store.busy) return
  const existing = workspace.selection.some(option => option.target.kind === target.kind && option.target.id === target.id)
  if (!existing && targets.value.length >= (store.capabilities?.max_targets || 1)) { notice.info(tr('已达到本轮对象上限')); return }
  workspace.select([...workspace.selection, { target: { kind: target.kind, id: target.id }, label: target.name }])
  void nextTick(() => composer.value?.focus())
}

let productionTimer: ReturnType<typeof setInterval> | undefined
function refreshVisibleState() {
  void refreshTargetStatus()
  void store.refreshProduction()
  void store.refreshConversations().catch(error => notice.error(error instanceof Error ? error.message : tr('加载助手失败')))
}
onBeforeUnmount(() => {
  catalogEpoch += 1; statusEpoch += 1
  window.removeEventListener('focus', refreshVisibleState)
  clearInterval(productionTimer)
  store.disconnect()
})
onMounted(() => {
  window.addEventListener('focus', refreshVisibleState)
  productionTimer = setInterval(() => {
    if (document.hidden) return
    void store.refreshProduction()
    void store.refreshConversations().catch(() => {})
  }, 4000)
})
</script>

<template>
  <aside class="creation-agent-panel" :class="{ 'is-workflow': workflow }" :aria-label="tr('创作助手')" @keydown.esc.stop="close">
    <header>
      <div><Bot :size="18" /><strong>{{ tr('创作助手') }}</strong></div>
      <div class="creation-agent-panel__header-actions"><AppButton v-if="bubbles.length" size="xs" icon-only :aria-label="allCollapsed ? tr('展开全部消息') : tr('折叠全部消息')" :title="allCollapsed ? tr('展开全部消息') : tr('折叠全部消息')" @click="toggleAllMessages"><ChevronsUpDown :size="15" /></AppButton>
      <AppButton size="xs" icon-only :aria-label="tr('关闭创作助手')" @click="close"><X :size="18" /></AppButton>
      </div>
    </header>
    <AgentConversationMenu :conversations="store.conversations" :deleted-conversations="store.deletedConversations" :current-id="store.conversationId" :workflow="workflow" :disabled="store.busy || store.loading || store.sessionBusy || operationBusy"
      @select="operation(() => store.selectConversation($event))" @create="newConversation"
      @delete="operation(() => store.deleteConversation($event))" @restore="operation(() => store.restoreConversation($event))" @load-deleted="operation(store.loadDeletedConversations)" @refresh="operation(store.refreshConversations)" />
    <div class="creation-agent-panel__context"><BookOpenText :size="13" /><span>{{ chapterLabel || tr('当前章节') }}</span>
      <AppSelect
        class="creation-agent-panel__scope-select"
        density="compact"
        :model-value="effectiveWriteScope"
        :ariaLabel="tr('助手操作范围')"
        :disabled="store.busy"
        :options="[
          ...(chapterId || targets.length ? [{ value: 'chapter', label: targets.length ? tr('指定对象') : tr('当前章') }] : []),
          { value: 'project', label: tr('全项目') },
          { value: 'read_only', label: tr('只查询') },
        ]"
        @update:model-value="changeWriteScope"
      />
    </div>
    <AgentSetupState v-if="store.loading || !ready" :capabilities="store.capabilities" :loading="store.loading" :error="store.error" @retry="store.open(projectId)" />
    <div v-else-if="!store.messages.length" class="creation-agent-panel__welcome">
      <span class="creation-agent-panel__welcome-icon"><Bot :size="27" /></span>
      <strong>{{ targets.length ? tr('想让画面怎样变化？') : tr('一起把故事变成画面') }}</strong>
      <p>{{ welcomeHint }}</p>
      <button v-for="suggestion in suggestions" :key="suggestion" type="button" class="creation-agent-panel__suggestion" @click="selectSuggestion(suggestion)">{{ suggestion }}</button>
      <span>{{ tr('每次修改都有记录，随时查看或撤销。') }}</span>
    </div>
    <AppButton v-if="store.nextBefore" size="xs" @click="operation(() => store.history(store.nextBefore || undefined))">{{ tr('查看更早的消息') }}</AppButton>
    <BubbleList v-if="store.messages.length" ref="messageList" class="creation-agent-panel__messages" :list="bubbles" :virtual="false" :auto-scroll="true" :show-back-button="true" max-height="100%">
      <template #content="{ item }">
        <AgentDisclosure class="creation-agent-panel__message-group" :class="{ 'is-assistant': item.role === 'assistant' }" :title="item.role === 'user' ? tr('你') : tr('创作助手')" :summary="item.preview" :open="messageIsOpen(item)" @update:open="toggleMessage(item.id, $event)">
        <AgentRunActivity v-if="item.role === 'assistant' && ([1, 2, 6].includes(item.activityStatus) || item.activity?.length || item.started_at || item.singleProductionResult)" :status="item.activityStatus" :operation-label="item.singleProductionResult ? productionLabel(item.singleProductionResult.operation) : undefined" :steps="item.activity" :started-at="item.started_at || item.created_at" :finished-at="item.finished_at" :status-text="store.currentRun?.task_id === item.task_id && [1, 2, 6].includes(item.status) ? store.statusText : undefined" @stream-update="messageList?.scrollToBottom(false)" />
        <div v-if="item.paragraphs.length" class="creation-agent-panel__message"><p v-for="(paragraph, index) in item.paragraphs" :key="index">{{ paragraph }}</p></div>
        <AgentQueryResults v-for="(result, index) in item.query_results || []" :key="index" :result="result" :disabled="store.busy"
          @locate="operation(() => locateQuery($event))" @select="selectQueryTarget" />
        <p v-if="item.role === 'assistant' && !item.singleProductionResult && (item.status === 4 || item.status === 5)" class="creation-agent-panel__round-status">{{ item.status === 5 ? tr('本轮已停止') : tr('本轮未完成') }}{{ item.changes.length ? tr('，已保存的修改见下方记录') : tr('，尚未保存修改') }}</p>
        <AgentRecoveryDetails v-if="item.recovery" :recovery="item.recovery" :failed="item.status === 4" :disabled="!writable || store.busy || operationBusy || suspended"
          @resume="operation(() => store.send({ resume_from_task_id: item.task_id, message: tr('继续失败步骤'), chapter_id: null, model_config_id: null, targets: [] }))" />
        <PromptChangeCard v-for="change in item.changes" :key="change.id" :change="change" :can-undo="Boolean(writable && !store.busy && !operationBusy)"
          @undo="operation(() => store.undo($event))" @locate="operation(() => locate($event))" />
        <div v-if="item.pending_production && item.status === 3" class="creation-agent-panel__production-confirmation">
          <p>{{ item.pending_production.intents.length && item.pending_production.intents.every(intent => intent.operation === 'prepare_export') ? tr('确认准备原片，不会提交付费画质增强。') : tr('请检查以下操作，确认后会调用模型并产生费用。') }}</p>
          <AgentPlanDetails v-if="item.pending_production.plan_confirmation" :plan="item.pending_production" />
          <ul v-else><li v-for="(proposal, index) in item.pending_production.labels" :key="index">{{ tr(({ story: '项目分析', assets: '提取', image: '生图', storyboard: '分镜', video: '视频', remake: '重制', compose: '合成', prepare_export: '准备当前原片', enhance_export: '增强到1080p' } as Record<string, string>)[proposal.operation] || proposal.operation) }} · {{ proposal.target_label }}</li></ul>
          <AppButton :disabled="!writable || store.busy || suspended" @click="confirmProduction(item.pending_production)">{{ item.pending_production.intents.length && item.pending_production.intents.every(intent => intent.operation === 'prepare_export') ? tr('准备当前原片') : tr('确认生成并计费') }}</AppButton>
        </div>
        <ul v-if="item.production?.length && !item.singleProductionResult" class="creation-agent-panel__production">
          <li v-for="receipt in item.production" :key="receipt.task_id">
            {{ productionLabel(receipt.operation) }} · {{ tr(({ 1: '等待中', 2: '处理中', 3: '已完成', 4: '失败', 5: '已取消', 6: '排队中' } as Record<number, string>)[receipt.status] || '未知') }}
            <span v-if="receipt.stage === 'billing_pending'">{{ tr('用量正在结算') }}</span>
            <span v-if="receipt.error">{{ receipt.error }}</span>
          </li>
        </ul>
        <p v-if="item.singleProductionResult?.error" class="creation-agent-panel__round-status">{{ item.singleProductionResult.error }}</p>
        <p v-if="item.singleProductionResult?.stage === 'billing_pending'" class="creation-agent-panel__round-status">{{ tr('用量正在结算') }}</p>
        <AgentUsageDetails v-if="item.role === 'assistant'" :usage="item.usage" />
        </AgentDisclosure>
      </template>
      <template #backToBottom="{ unreadCount, scrollToBottom }"><AppButton size="xs" variant="secondary" @click="scrollToBottom()">{{ unreadCount ? tr('{p0} 条新消息', { p0: unreadCount }) : tr('回到最新') }}</AppButton></template>
    </BubbleList>
    <footer v-if="ready && !store.loading">
      <AgentDisclosure v-if="(!store.busy && (store.currentRun?.usage.turn_limited || store.currentRun?.status === 4 || store.currentRun?.status === 5)) || store.error || pendingCount || statusError" v-model:open="statusOpen" class="creation-agent-panel__run-details" :title="statusLabel">
        <template #title><AgentActivity :text="statusLabel" :active="false" /></template>
        <template #actions><button v-if="pendingCount" type="button" class="creation-agent-panel__pending-chip" :title="tr('{p0} 个对象有新设定待应用', { p0: pendingCount })" @click="pickerOpen = true">{{ tr('新要求') }} {{ pendingCount }}</button></template>
      <template v-if="store.currentRun?.recovery?.can_resume_production">
        <AppButton size="xs" :disabled="store.busy || store.submitting" @click="store.resume()">{{ store.submitting ? tr('正在恢复…') : tr('从断点继续') }}</AppButton>
        <p class="creation-agent-panel__round-status">{{ tr('复用已完成步骤；已扣费但结果缺失的步骤直接重做，会产生新费用。执行中的请求不会重复提交。') }}</p>
      </template>
      <AppButton v-else-if="!store.busy && (store.currentRun?.usage.turn_limited || store.currentRun?.status === 4)" size="xs" @click="composer?.focus()">{{ tr('继续对话') }}</AppButton>
      <p v-if="store.error" class="creation-agent-panel__error" role="alert">{{ store.error }}<template v-if="failedRequest"><AppButton size="xs" @click="editFailedRequest">{{ tr('编辑后重试') }}</AppButton><AppButton size="xs" @click="router.push('/settings')">{{ tr('查看设置') }}</AppButton></template><AppButton v-else-if="!store.busy" size="xs" @click="store.open(projectId)">{{ tr('重新连接') }}</AppButton></p>
      <AppButton v-if="store.currentRun && !store.streamConnected && store.busy && store.error" size="xs" @click="store.follow(store.currentRun.task_id)"><RefreshCw :size="13" />{{ tr('重新连接') }}</AppButton>
      <p v-if="pendingCount" class="creation-agent-panel__constraint-notice"><button type="button" @click="pickerOpen = true">{{ pendingCount }} {{ tr('个对象有新设定待应用') }} <span>{{ tr('查看') }}</span></button></p>
      <p v-if="statusError && (pickerOpen || targets.length)" class="creation-agent-panel__constraint-notice" role="status">{{ statusError }}</p>
      </AgentDisclosure>
      <AgentComposer ref="composer" v-model="draft" v-model:model-id="modelId" :models="store.capabilities?.models || []" :disabled="!ready || store.loading || store.sessionBusy || operationBusy || suspended" :busy="store.busy" :submitting="store.submitting" @submit="send" @stop="operation(store.stop)">
        <template #context>
          <AgentDisclosure v-if="targets.length" class="creation-agent-panel__references" :title="tr('引用 {p0}', { p0: targets.length })" :summary="workspace.selection.map(option => option.label).join('、')">
          <div class="creation-agent-panel__selected" :aria-label="tr('已选修改对象')">
            <span v-for="option in workspace.selection" :key="targetKey(option.target)" :title="option.label"><span class="creation-agent-panel__selected-label">{{ option.label.replace(/@\{([^{}]+)\}/g, '$1') }}</span><button type="button" :disabled="store.busy" :aria-label="tr('移除{p0}', { p0: option.label })" @click="removeTarget(option)"><X :size="12" /></button></span>
          </div>
          </AgentDisclosure>
        </template>
        <template #tools>
          <AgentTargetPicker v-model="selected" v-model:open="pickerOpen" :options="allOptions" :limit="store.capabilities?.max_targets || 1" :loading="catalogLoading" :has-more="hasMoreAssets || hasMoreScenes" :disabled="store.busy" :pending="pendingConstraints" @refresh="loadTargets()" @more="loadTargets(true)" @done="nextTick(() => composer?.focus())" />
        </template>
      </AgentComposer>
      <p class="creation-agent-panel__boundary">{{ tr('操作可撤销') }}<span>{{ tr('Enter 发送 · Shift + Enter 换行') }}</span></p>
    </footer>
  </aside>
</template>

<style scoped>
.creation-agent-panel { --el-color-primary: var(--app-accent); --el-bg-color: var(--app-surface); --el-bg-color-overlay: var(--app-surface); --el-fill-color: var(--app-surface-muted); --el-fill-color-light: var(--app-surface-muted); --el-fill-color-blank: var(--app-surface); --el-text-color-primary: var(--app-text); --el-text-color-regular: var(--app-text-secondary); --el-border-color: var(--app-border); --el-border-color-light: var(--app-border); --el-border-radius-base: 10px; --el-font-size-base: 13px; --el-font-line-height-primary: 1.65; position: sticky; top: var(--short-drama-header-height, 72px); flex: 0 0 var(--short-drama-assistant-width, 420px); width: var(--short-drama-assistant-width, 420px); min-width: 0; height: calc(100dvh - var(--short-drama-header-height, 72px)); display: flex; flex-direction: column; border-left: 1px solid var(--app-border); color: var(--app-text); background: var(--app-surface); overflow: hidden; font-size: 13px; }
.creation-agent-panel > header,.creation-agent-panel__toolbar,.creation-agent-panel__scope,.creation-agent-panel__context,.creation-agent-panel__selected,.creation-agent-panel > footer { flex-shrink: 0; }
.creation-agent-panel > header { display: flex; align-items: center; justify-content: space-between; padding: 4px 10px; min-height: 38px; border-bottom: 1px solid var(--app-border); }
.creation-agent-panel header > div { display: flex; align-items: center; gap: 8px; }
.creation-agent-panel__constraint-notice { margin: 0 2px 8px; color: var(--app-text-secondary); font-size: 12px; line-height: 1.6; }
.creation-agent-panel__hint { padding: 10px 16px; color: var(--app-text-secondary); }
.creation-agent-panel__welcome { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; align-items: flex-start; justify-content: safe center; padding: 24px; gap: 14px; }
.creation-agent-panel__welcome-icon { flex-shrink: 0; display: grid; width: 48px; height: 48px; place-items: center; color: var(--app-accent); border-radius: 15px; background: var(--app-accent-soft); }
.creation-agent-panel__welcome > strong { font-size: 17px; }
.creation-agent-panel__suggestion { width: 100%; padding: 12px; text-align: left; color: var(--app-text-secondary); border: 1px solid var(--app-border); border-radius: 11px; background: var(--app-surface); font: inherit; line-height: 1.6; cursor: pointer; }
.creation-agent-panel__suggestion:hover { color: var(--app-accent); background: var(--app-accent-soft); border-color: var(--app-accent); }
.creation-agent-panel__context { display: flex; align-items: center; gap: 6px; min-width: 0; padding: 2px 12px 5px; color: var(--app-text-muted); font-size: 11px; border-bottom: 1px solid var(--app-border); }
.creation-agent-panel__context span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.creation-agent-panel__scope-select { margin-left: auto; flex-shrink: 0; }
.creation-agent-panel__selected { display: flex; flex-wrap: wrap; gap: 4px; max-height: 72px; overflow: auto; padding: 0 2px; }
.creation-agent-panel__selected > span { display: flex; align-items: center; gap: 5px; max-width: 100%; padding: 4px 7px; border-radius: 6px; color: var(--app-accent); background: var(--app-accent-soft); font-size: 11px; overflow-wrap: anywhere; }
.creation-agent-panel__selected-label { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.creation-agent-panel__selected button { flex: none; display: grid; place-items: center; min-width: 22px; min-height: 22px; color: inherit; background: transparent; cursor: pointer; }
.creation-agent-panel__welcome p { color: var(--app-text-secondary); line-height: 1.8; margin: 0; }
.creation-agent-panel__welcome span { font-size: 12px; color: var(--app-text-secondary); }
.creation-agent-panel__messages { flex: 1; min-width: 0; min-height: 0; padding: 8px 12px; overflow-y: auto; overflow-x: hidden; }
.creation-agent-panel__production { list-style: none; margin: 6px 0; padding: 0; color: var(--app-text-secondary); font-size: 12px; line-height: 1.7; }
.creation-agent-panel__production li + li { margin-top: 3px; }
.creation-agent-panel__message-group.is-assistant :deep(.agent-disclosure__toggle) { width: fit-content; flex: none; font-size: 12px; }
.creation-agent-panel__message-group.is-assistant :deep(.agent-disclosure__title) { color: var(--app-text); font-weight: 600; }
.creation-agent-panel__message-group.is-assistant :deep(.agent-disclosure__body) { padding: 2px 0 0; }
.creation-agent-panel__message { overflow-wrap: anywhere; line-height: 1.65; }
.creation-agent-panel__message p { margin: 0; white-space: pre-wrap; }.creation-agent-panel__message p + p { margin-top: 6px; }
.creation-agent-panel > footer { padding: 4px 10px 6px; border-top: 1px solid var(--app-border); margin-top: auto; background: var(--app-surface); max-height: 48%; overflow-y: auto; }
.creation-agent-panel__status { color: var(--app-text-secondary); margin-bottom: 8px; font-size: 12px; }
.creation-agent-panel__constraint-notice button { color: inherit; background: transparent; font: inherit; cursor: pointer; }.creation-agent-panel__constraint-notice button span { color: var(--app-accent); margin-left: 6px; }
.creation-agent-panel__boundary { display: flex; justify-content: space-between; gap: 6px; margin: 5px 2px 0; font-size: 10px; color: var(--app-text-muted); }
.creation-agent-panel__references { padding: 2px 8px 0; box-sizing: border-box; }
.creation-agent-panel__run-details { margin-bottom: 4px; }
.creation-agent-panel__pending-chip { padding: 3px 6px; flex-shrink: 0; border-radius: 5px; color: var(--app-text-secondary); background: var(--app-surface-muted); font: inherit; font-size: 10px; cursor: pointer; }
.creation-agent-panel__pending-chip:hover { color: var(--app-accent); background: var(--app-accent-soft); }
.creation-agent-panel__pending-chip:focus-visible { outline: 2px solid var(--app-accent); }
.creation-agent-panel :deep(.elx-bubble-list__list) { gap: 10px; }
.creation-agent-panel :deep(.elx-bubble__content) { padding: 2px 8px; border-radius: 9px; min-height: 0; white-space: normal; }
.creation-agent-panel :deep(.elx-bubble--start .elx-bubble__content-wrapper .elx-bubble__content) { width: 100%; padding: 0; border: 0; border-radius: 0; min-height: 0; background: transparent; box-shadow: none; }
.creation-agent-panel :deep(.elx-bubble__footer:empty) { display: none; }
.creation-agent-panel :deep(.elx-bubble__content-wrapper) { gap: 0; }
.creation-agent-panel :deep(.elx-bubble--end .agent-disclosure__summary) { color: var(--app-text); }
.creation-agent-panel__round-status { color: var(--app-text-secondary); margin: 6px 0; font-size: 11px; }
.creation-agent-panel__error { color: var(--app-text); border-left: 3px solid var(--app-accent); padding-left: 8px; font-size: 12px; }
.creation-agent-panel :deep(.elx-bubble__avatar-placeholder) { display: none; }
.creation-agent-panel :deep(.elx-bubble__content-wrapper), .creation-agent-panel :deep(.elx-bubble__content) { min-width: 0; max-width: 100%; }
.creation-agent-panel :deep(.elx-bubble__footer) { min-width: 0; width: 100%; max-width: 100%; }
.creation-agent-panel :deep(.elx-bubble__content--filled) { background: var(--app-accent-soft); }
.creation-agent-panel :deep([contenteditable]) { color: var(--app-text); max-height: 160px; overflow-y: auto; }
@media (max-width: 760px) { .creation-agent-panel { flex: 1 1 100%; width: 100%; border-left: 0; } }
</style>
