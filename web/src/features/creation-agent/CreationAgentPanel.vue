<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { BubbleList } from 'vue-element-plus-x'
import type { BubbleListInstance } from 'vue-element-plus-x/types/BubbleList'
import { Bot, History, Plus, RefreshCw, X, Search, ChevronDown, BookOpenText } from 'lucide-vue-next'
import { api } from '@/api'
import AppButton from '@/components/AppButton.vue'
import AppBadge from '@/components/AppBadge.vue'
import { notice } from '@/shared/notice'
import { useCreationAgentStore } from './store'
import { agentApi } from './api'
import PromptChangeCard from './PromptChangeCard.vue'
import AgentComposer from './AgentComposer.vue'
import AgentSetupState from './AgentSetupState.vue'
import { targetKey, useCreationAgentWorkspace, type AgentTargetOption } from './workspace'
import type { AgentChange, AgentChangeItem, AgentTarget, PromptTargetStatus } from './types'

const props = defineProps<{ projectId: number; chapterId: number; selectedTargets?: AgentTarget[]; workflow?: boolean; chapterLabel?: string; phase?: 'script' | 'settings' | 'storyboard' | 'video' }>()
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
const search = ref('')
const kindFilter = ref<'all' | 'scene' | 'image'>('all')
const options = ref<{ key: string; target: AgentTarget; label: string }[]>([])
const pickerOpen = ref(false)
const catalogLoading = ref(false)
const catalogPage = ref(1)
const hasMoreAssets = ref(false)
const hasMoreScenes = ref(false)
const operationBusy = ref(false)
const pendingConstraints = ref<Record<string, PromptTargetStatus['pending_constraints']>>({})
const statusError = ref('')
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
const filteredOptions = computed(() => allOptions.value.filter(option =>
  (kindFilter.value === 'all' || (kindFilter.value === 'scene' ? option.target.kind === 'scene' : option.target.kind !== 'scene'))
  && option.label.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase())))
const suggestions = computed(() => targets.value.length ? [
  '光线更柔和，保留人物外貌和服装。',
  '画面更有电影感，每个分镜独立完整描述。',
] : ['先聊聊这个故事适合怎样的画面风格。', '帮我梳理人物与场景需要保持一致的设定。'])
const welcomeHint = computed(() => targets.value.length ? '说出你的想法，助手会直接调整选中的提示词。'
  : props.phase === 'script' ? '先聊风格和人物设定。确认故事后，在设定页提取本章资产，就可以开始调整画面。'
    : props.phase === 'storyboard' ? '点击分镜上的“用助手修改”，或从上方选择多个分镜，一起调整。'
      : '可以先聊风格和人物设定；要修改画面，点击页面上的“用助手修改”。')

function applyDefaults() {
  if (workspace.scopeEdited || store.busy) return
  workspace.select((props.selectedTargets ?? []).map(target => options.value.find(option => option.key === targetKey(target))
    ?? { target, label: target.kind === 'scene' ? '当前分镜' : '当前图片设定' }), false)
}

function selectSuggestion(text: string) { draft.value = text; void nextTick(() => composer.value?.focus()) }
function removeTarget(option: AgentTargetOption) {
  if (!store.busy) workspace.select(workspace.selection.filter(item => targetKey(item.target) !== targetKey(option.target)))
}
const bubbles = computed(() => store.messages.map(message => ({ ...message,
  placement: message.role === 'user' ? 'end' as const : 'start' as const,
  variant: message.role === 'user' ? 'filled' as const : 'borderless' as const,
  maxWidth: '100%', loading: message.role === 'assistant' && !message.content && store.busy,
})))

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
      { key: `asset:${asset.id}`, target: { kind: 'asset' as const, id: asset.id }, label: asset.canonical_name },
      ...(asset.variants ?? []).map(variant => ({ key: `variant:${variant.id}`, target: { kind: 'variant' as const, id: variant.id }, label: `${asset.canonical_name} · ${variant.name}` })),
    ])
    const addedOptions = [
      ...(scenes?.data.items ?? []).map(scene => ({ key: `scene:${scene.id}`, target: { kind: 'scene' as const, id: scene.id }, label: `镜头 ${scene.sequence} · ${scene.description || '未命名'}` })), ...assetOptions,
    ]
    options.value = more ? [...options.value, ...addedOptions] : addedOptions
    catalogPage.value = page
    hasMoreAssets.value = page < (assets?.data.pagination.pages ?? 0)
    hasMoreScenes.value = page < (scenes?.data.pagination.pages ?? 0)
    if (!more) applyDefaults()
    await refreshTargetStatus()
  } catch (error) { notice.error(error instanceof Error ? error.message : '无法加载当前对象') }
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
    if (epoch === statusEpoch) statusError.value = '暂时无法核对新约束，请稍后重新打开对象列表。'
  }
}

watch(() => props.projectId, id => { workspace.enterProject(id); void store.open(id) }, { immediate: true })
watch(() => [props.projectId, props.chapterId], () => {
  workspace.enterChapter(props.chapterId)
  search.value = ''
  void loadTargets()
}, { immediate: true })
watch(() => store.capabilities?.models, models => {
  if (!models?.some(model => String(model.id) === modelId.value)) modelId.value = String(models?.[0]?.id ?? '')
})
watch(() => (props.selectedTargets ?? []).map(targetKey).join('|'), applyDefaults)
watch(() => [ready.value, store.loading], () => {
  if (ready.value && !store.loading) void nextTick(() => { composer.value?.focus(); messageList.value?.scrollToBottom(false) })
})
watch(() => workspace.focusRevision, () => { pickerOpen.value = false; void refreshTargetStatus(); void nextTick(() => composer.value?.focus()) })
watch(() => store.conversationId, (id, previous) => {
  if (id && !previous && store.submitting && workspace.drafts.new) {
    workspace.drafts[`conversation:${id}`] = workspace.drafts.new
    workspace.drafts.new = ''
  }
})
watch(() => store.changesRevision, () => emit('changed', store.latestChanges))
watch(() => [store.busy, store.changesRevision], () => { if (!store.busy) void refreshTargetStatus() })
watch(pickerOpen, open => { if (open) void refreshTargetStatus() })

async function send(text: string) {
  if (!text.trim() || !ready.value || store.busy) return
  const key = draftKey.value
  if (await store.send({ message: text.trim(), chapter_id: props.chapterId || null, model_config_id: Number(modelId.value) || null, targets: targets.value })) {
    workspace.drafts[key] = ''
    // The first accepted request creates a conversation with its own draft slot.
    workspace.drafts[draftKey.value] = ''
    await nextTick()
    messageList.value?.scrollToBottom(false)
  }
}

async function operation(action: () => Promise<unknown>) {
  operationBusy.value = true
  try { await action() } catch (error) { notice.error(error instanceof Error ? error.message : '操作失败') }
  finally { operationBusy.value = false }
}

function editFailedRequest() {
  if (failedRequest.value) selectSuggestion(failedRequest.value)
}

function conversationLabel(conversation: { id: number; updated_at: string; title?: string }) {
  if (conversation.title) return conversation.title
  if (!conversation.updated_at) return `对话 ${conversation.id}`
  const updatedAt = new Date(conversation.updated_at)
  if (Number.isNaN(updatedAt.getTime())) return `对话 ${conversation.id}`
  const time = new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(updatedAt)
  return `对话 ${conversation.id} · ${time}`
}

function close() {
  emit('close')
}

async function locate(target: AgentChangeItem) {
  if (target.kind === 'scene') {
    const scene = (await api.scene(target.target_id)).data
    await router.push({ path: `/create/short-drama/storyboard/${props.projectId}`, query: { chapter: scene.chapter_id, scene: scene.id } })
  } else {
    const assetId = target.kind === 'variant' ? target.asset_id : target.target_id
    if (!assetId) throw new Error('这条历史记录缺少所属资产信息，请从设定页选择对应形象。')
    await router.push({ path: `/create/short-drama/manual/${props.projectId}`, query: { chapter: props.chapterId || undefined, asset: assetId, variant: target.kind === 'variant' ? target.target_id : undefined } })
  }
}

onBeforeUnmount(() => { catalogEpoch += 1; statusEpoch += 1; window.removeEventListener('focus', refreshTargetStatus); store.disconnect() })
onMounted(() => window.addEventListener('focus', refreshTargetStatus))
</script>

<template>
  <aside class="creation-agent-panel" :class="{ 'is-workflow': workflow }" aria-label="创作助手" @keydown.esc.stop="close">
    <header>
      <div><Bot :size="18" /><strong>创作助手</strong></div>
      <AppButton size="sm" icon-only aria-label="关闭创作助手" @click="close"><X :size="18" /></AppButton>
    </header>
    <div class="creation-agent-panel__toolbar" aria-label="对话管理">
      <label class="creation-agent-panel__conversation-select">
        <History :size="15" aria-hidden="true" />
        <span>对话记录</span>
        <select aria-label="对话记录" :value="store.conversationId || ''" :disabled="store.busy || store.loading || operationBusy || !store.conversations.length" @change="operation(() => store.selectConversation(Number(($event.target as HTMLSelectElement).value)))">
          <option v-if="!store.conversations.length" value="">暂无记录</option>
          <option v-for="conversation in store.conversations" :key="conversation.id" :value="conversation.id">{{ conversationLabel(conversation) }}</option>
        </select>
      </label>
      <AppButton size="sm" variant="soft" aria-label="新建对话" :disabled="store.busy || operationBusy || store.loading || !ready" @click="operation(store.newConversation)"><Plus :size="15" />新会话</AppButton>
    </div>
    <div class="creation-agent-panel__context"><BookOpenText :size="13" /><span>{{ chapterLabel || '当前章节' }}</span></div>
    <div v-if="!store.loading && store.capabilities" class="creation-agent-panel__scope">
      <AppButton size="xs" :aria-expanded="pickerOpen" @click="pickerOpen = !pickerOpen"><ChevronDown :size="13" />{{ targets.length ? `修改范围：已选 ${targets.length} 个对象` : '选择需要修改的对象' }}</AppButton>
      <span>仅图片与分镜提示词</span>
    </div>
    <div v-if="targets.length && !pickerOpen" class="creation-agent-panel__selected" aria-label="已选修改对象">
      <span v-for="option in workspace.selection" :key="targetKey(option.target)" :title="option.label"><span class="creation-agent-panel__selected-label">{{ option.label }}</span><button type="button" :disabled="store.busy" :aria-label="`移除${option.label}`" @click="removeTarget(option)"><X :size="12" /></button></span>
    </div>
    <p v-if="pendingCount" class="creation-agent-panel__constraint-notice" role="status">当前可选对象中有 {{ pendingCount }} 个需核对新约束，历史提示词尚未自动更新。<AppButton size="xs" @click="pickerOpen = true">查看对象</AppButton></p>
    <p v-if="statusError" class="creation-agent-panel__constraint-notice" role="status">{{ statusError }}</p>
    <div v-if="pickerOpen" class="creation-agent-panel__picker" aria-label="修改对象">
      <div class="creation-agent-panel__search"><Search :size="14" /><input v-model="search" type="search" aria-label="搜索修改对象" placeholder="搜索角色、场景或分镜" /></div>
      <nav class="creation-agent-panel__filters" aria-label="对象类型">
        <AppButton size="xs" :active="kindFilter === 'all'" @click="kindFilter = 'all'">全部</AppButton>
        <AppButton size="xs" :active="kindFilter === 'image'" @click="kindFilter = 'image'">图片设定</AppButton>
        <AppButton size="xs" :active="kindFilter === 'scene'" @click="kindFilter = 'scene'">分镜</AppButton>
        <span>最多 {{ store.capabilities?.max_targets || 1 }} 个</span>
      </nav>
      <AppButton size="xs" :loading="catalogLoading" @click="loadTargets()"><RefreshCw :size="12" />刷新对象</AppButton>
      <p v-if="catalogLoading">正在加载…</p>
      <label v-for="option in filteredOptions" :key="option.key">
        <input v-model="selected" type="checkbox" :value="option.key" :disabled="store.busy || (!selected.includes(option.key) && selected.length >= (store.capabilities?.max_targets || 1))" />
        <span>{{ option.label }} <AppBadge v-if="pendingConstraints[option.key]?.length" tone="warning" size="sm">待核对约束</AppBadge>
          <small v-for="rule in pendingConstraints[option.key]" :key="rule.id" class="creation-agent-panel__pending-rule">{{ rule.content }}</small>
        </span>
      </label>
      <p v-if="!catalogLoading && !filteredOptions.length">{{ search ? '没有匹配对象，可加载更多或从页面点击“用助手修改”。' : '当前章节还没有可修改的对象。先提取资产或生成分镜。' }}</p>
      <AppButton v-if="hasMoreAssets || hasMoreScenes" size="xs" :loading="catalogLoading" @click="loadTargets(true)">加载更多对象</AppButton>
    </div>
    <AgentSetupState v-if="store.loading || !ready" :capabilities="store.capabilities" :loading="store.loading" :error="store.error" @retry="store.open(projectId)" />
    <div v-else-if="!store.messages.length" class="creation-agent-panel__welcome">
      <span class="creation-agent-panel__welcome-icon"><Bot :size="27" /></span>
      <strong>{{ targets.length ? '想让画面怎样变化？' : '一起把故事变成画面' }}</strong>
      <p>{{ welcomeHint }}</p>
      <button v-for="suggestion in suggestions" :key="suggestion" type="button" class="creation-agent-panel__suggestion" @click="selectSuggestion(suggestion)">{{ suggestion }}</button>
      <span>每次修改都有记录，随时查看或撤销。</span>
    </div>
    <AppButton v-if="store.nextBefore" size="xs" @click="operation(() => store.history(store.nextBefore || undefined))">查看更早的消息</AppButton>
    <BubbleList v-if="store.messages.length" ref="messageList" class="creation-agent-panel__messages" :list="bubbles" :virtual="false" :auto-scroll="true" :show-back-button="true" max-height="100%">
      <template #content="{ item }"><div class="creation-agent-panel__message">{{ item.content }}</div></template>
      <template #footer="{ item }">
        <p v-if="item.role === 'assistant' && (item.status === 4 || item.status === 5)" class="creation-agent-panel__round-status">{{ item.status === 5 ? '本轮已停止' : '本轮未完成' }}{{ item.changes.length ? '，已保存的修改见下方记录' : '，尚未保存修改' }}</p>
        <PromptChangeCard v-for="change in item.changes" :key="change.id" :change="change" :can-undo="Boolean(writable && !store.busy && !operationBusy)"
          @undo="operation(() => store.undo($event))" @locate="operation(() => locate($event))" />
      </template>
      <template #backToBottom="{ unreadCount, scrollToBottom }"><AppButton size="xs" variant="secondary" @click="scrollToBottom()">{{ unreadCount ? `${unreadCount} 条新消息` : '回到最新' }}</AppButton></template>
    </BubbleList>
    <footer v-if="ready && !store.loading">
      <div v-if="store.statusText" class="creation-agent-panel__status" role="status">{{ store.statusText }}</div>
      <p v-if="store.error" class="creation-agent-panel__error" role="alert">{{ store.error }}<template v-if="failedRequest"><AppButton size="xs" @click="editFailedRequest">编辑后重试</AppButton><AppButton size="xs" @click="router.push('/settings')">查看设置</AppButton></template><AppButton v-else-if="!store.busy" size="xs" @click="store.open(projectId)">重新连接</AppButton></p>
      <AppButton v-if="store.currentRun && !store.streamConnected && store.busy" size="xs" @click="store.follow(store.currentRun.task_id)"><RefreshCw :size="13" />重新连接</AppButton>
      <AgentComposer ref="composer" v-model="draft" v-model:model-id="modelId" :models="store.capabilities?.models || []" :disabled="!ready" :busy="store.busy" :submitting="store.submitting" @submit="send" @stop="operation(store.stop)" />
    </footer>
  </aside>
</template>

<style scoped>
.creation-agent-panel { --el-color-primary: var(--app-accent); --el-bg-color: var(--app-surface); --el-bg-color-overlay: var(--app-surface); --el-fill-color: var(--app-surface-muted); --el-fill-color-light: var(--app-surface-muted); --el-fill-color-blank: var(--app-surface); --el-text-color-primary: var(--app-text); --el-text-color-regular: var(--app-text-secondary); --el-border-color: var(--app-border); --el-border-color-light: var(--app-border); --el-border-radius-base: 10px; --el-font-size-base: 13px; --el-font-line-height-primary: 1.65; position: sticky; top: var(--short-drama-header-height, 72px); flex: 0 0 var(--short-drama-assistant-width, 420px); width: var(--short-drama-assistant-width, 420px); min-width: 0; height: calc(100dvh - var(--short-drama-header-height, 72px)); display: flex; flex-direction: column; border-left: 1px solid var(--app-border); color: var(--app-text); background: var(--app-surface); overflow: hidden; font-size: 13px; }
.creation-agent-panel > header,.creation-agent-panel__toolbar,.creation-agent-panel__scope,.creation-agent-panel__context,.creation-agent-panel__selected,.creation-agent-panel > footer { flex-shrink: 0; }
.creation-agent-panel header { display: flex; align-items: center; justify-content: space-between; padding: 12px 14px; border-bottom: 1px solid var(--app-border); }
.creation-agent-panel header > div { display: flex; align-items: center; gap: 8px; }
.creation-agent-panel__toolbar { display: flex; align-items: center; gap: 8px; padding: 10px 12px 4px; }
.creation-agent-panel__conversation-select { min-width: 0; flex: 1; display: grid; grid-template-columns: auto auto minmax(0, 1fr); align-items: center; gap: 6px; min-height: 34px; padding: 0 8px; color: var(--app-text-secondary); border: 1px solid var(--app-border); border-radius: 9px; background: var(--app-surface); }
.creation-agent-panel__conversation-select > span { white-space: nowrap; font-size: 11px; }
.creation-agent-panel select { min-width: 0; color: var(--app-text-secondary); background: var(--app-surface); border: 1px solid var(--app-border); border-radius: 8px; padding: 6px; font: inherit; }
.creation-agent-panel__conversation-select select { width: 100%; border: 0; padding-inline: 2px; background: transparent; text-overflow: ellipsis; }
.creation-agent-panel__scope { padding: 6px 10px; display: flex; flex-wrap: wrap; align-items: center; gap: 4px; }
.creation-agent-panel__scope > span { color: var(--app-text-secondary); font-size: 11px; }
.creation-agent-panel__constraint-notice { margin: 4px 12px; color: var(--app-text-secondary); font-size: 12px; line-height: 1.6; }
.creation-agent-panel__pending-rule { display: block; margin-top: 3px; color: var(--app-text-secondary); line-height: 1.5; }
.creation-agent-panel__picker { max-height: min(300px, 38dvh); overflow: auto; flex-shrink: 0; margin: 0 12px; padding: 8px; border: 1px solid var(--app-border); border-radius: 10px; }
.creation-agent-panel__picker label { display: flex; align-items: flex-start; gap: 8px; padding: 6px 0; overflow-wrap: anywhere; }
.creation-agent-panel__picker input { accent-color: var(--app-accent); }
.creation-agent-panel__hint { padding: 10px 16px; color: var(--app-text-secondary); }
.creation-agent-panel__welcome { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; align-items: flex-start; justify-content: safe center; padding: 24px; gap: 14px; }
.creation-agent-panel__welcome-icon { flex-shrink: 0; display: grid; width: 48px; height: 48px; place-items: center; color: var(--app-accent); border-radius: 15px; background: var(--app-accent-soft); }
.creation-agent-panel__welcome > strong { font-size: 17px; }
.creation-agent-panel__suggestion { width: 100%; padding: 12px; text-align: left; color: var(--app-text-secondary); border: 1px solid var(--app-border); border-radius: 11px; background: var(--app-surface); font: inherit; line-height: 1.6; cursor: pointer; }
.creation-agent-panel__suggestion:hover { color: var(--app-accent); background: var(--app-accent-soft); border-color: var(--app-accent); }
.creation-agent-panel__context { display: flex; align-items: center; gap: 6px; min-width: 0; padding: 10px 14px 2px; color: var(--app-text-muted); font-size: 11px; }
.creation-agent-panel__context span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.creation-agent-panel__selected { display: flex; flex-wrap: wrap; gap: 5px; max-height: 82px; overflow: auto; padding: 2px 14px 8px; }
.creation-agent-panel__selected > span { display: flex; align-items: center; gap: 5px; max-width: 100%; padding: 4px 7px; border-radius: 6px; color: var(--app-accent); background: var(--app-accent-soft); font-size: 11px; overflow-wrap: anywhere; }
.creation-agent-panel__selected-label { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.creation-agent-panel__selected button { flex: none; display: grid; place-items: center; min-width: 22px; min-height: 22px; color: inherit; background: transparent; cursor: pointer; }
.creation-agent-panel__search { display: flex; align-items: center; gap: 7px; padding: 7px 9px; border: 1px solid var(--app-border); border-radius: 8px; color: var(--app-text-muted); }
.creation-agent-panel__search input { width: 100%; min-width: 0; padding: 0; color: var(--app-text); background: transparent; border: 0; font: inherit; outline: none; }
.creation-agent-panel__search:focus-within { border-color: var(--app-accent); }
.creation-agent-panel__filters { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; padding-block: 8px; }
.creation-agent-panel__filters > span { margin-left: auto; color: var(--app-text-muted); font-size: 11px; }
.creation-agent-panel__welcome p { color: var(--app-text-secondary); line-height: 1.8; margin: 0; }
.creation-agent-panel__welcome span { font-size: 12px; color: var(--app-text-secondary); }
.creation-agent-panel__messages { flex: 1; min-height: 0; padding: 10px 14px; overflow: auto; }
.creation-agent-panel__message { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.7; }
.creation-agent-panel footer { padding: 12px; border-top: 1px solid var(--app-border); margin-top: auto; background: color-mix(in srgb,var(--app-surface) 96%,var(--app-accent)); }
.creation-agent-panel__status { color: var(--app-text-secondary); margin-bottom: 8px; font-size: 12px; }
.creation-agent-panel__round-status { color: var(--app-text-secondary); margin: 6px 0; font-size: 11px; }
.creation-agent-panel__error { color: var(--app-text); border-left: 3px solid var(--app-accent); padding-left: 8px; font-size: 12px; }
.creation-agent-panel :deep(.elx-bubble__avatar-placeholder) { display: none; }
.creation-agent-panel :deep(.elx-bubble__content--filled) { background: var(--app-accent-soft); }
.creation-agent-panel :deep([contenteditable]) { color: var(--app-text); max-height: 160px; overflow-y: auto; }
@media (max-width: 760px) { .creation-agent-panel { flex: 1 1 100%; width: 100%; border-left: 0; } }
</style>
