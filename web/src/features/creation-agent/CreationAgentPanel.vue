<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { BubbleList, XSender } from 'vue-element-plus-x'
import { Bot, History, Plus, RefreshCw, Sparkles, X, ArrowUp, Square } from 'lucide-vue-next'
import { api } from '@/api'
import AppButton from '@/components/AppButton.vue'
import AppBadge from '@/components/AppBadge.vue'
import { notice } from '@/shared/notice'
import { useCreationAgentStore } from './store'
import { agentApi } from './api'
import PromptChangeCard from './PromptChangeCard.vue'
import type { AgentChange, AgentChangeItem, AgentTarget, PromptTargetStatus } from './types'

const props = defineProps<{ projectId: number; chapterId: number; selectedTargets?: AgentTarget[]; workflow?: boolean }>()
const emit = defineEmits<{ close: []; changed: [changes: AgentChange[]] }>()
const store = useCreationAgentStore()
const router = useRouter()
const panel = ref<HTMLElement | null>(null)
const sender = ref<InstanceType<typeof XSender> | null>(null)
const modelId = ref('')
const selected = ref<string[]>([])
const scopeEdited = ref(false)
const options = ref<{ key: string; target: AgentTarget; label: string }[]>([])
const pickerOpen = ref(false)
const catalogLoading = ref(false)
const catalogPage = ref(1)
const hasMoreAssets = ref(false)
const hasMoreScenes = ref(false)
const operationBusy = ref(false)
const pendingConstraints = ref<Record<string, PromptTargetStatus['pending_constraints']>>({})
const statusError = ref('')
const pendingCount = computed(() => options.value.filter(option => pendingConstraints.value[option.key]?.length).length)
let catalogEpoch = 0
let statusEpoch = 0
let senderObserver: MutationObserver | null = null
const writable = computed(() => store.capabilities?.enabled && store.capabilities.can_write)
const targets = computed(() => options.value.filter(option => selected.value.includes(option.key)).map(option => option.target))
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
    if (!more) {
      selected.value = (props.selectedTargets ?? []).map(target => `${target.kind}:${target.id}`)
      scopeEdited.value = false
    }
    await refreshTargetStatus()
  } catch (error) { notice.error(error instanceof Error ? error.message : '无法加载当前对象') }
  finally { if (epoch === catalogEpoch) catalogLoading.value = false }
}

async function refreshTargetStatus() {
  const epoch = ++statusEpoch
  const projectId = props.projectId
  const chapterId = props.chapterId
  const currentTargets = options.value.map(option => option.target)
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

watch(() => [props.projectId, props.chapterId], async () => {
  await Promise.all([store.open(props.projectId), loadTargets()])
  modelId.value = String(store.capabilities?.models[0]?.id ?? '')
}, { immediate: true })
watch(() => (props.selectedTargets ?? []).map(target => `${target.kind}:${target.id}`).join('|'), () => {
  if (!scopeEdited.value && !store.busy && props.selectedTargets?.length) selected.value = props.selectedTargets.map(target => `${target.kind}:${target.id}`)
})
watch(() => store.changesRevision, () => emit('changed', store.latestChanges))
watch(() => [store.busy, store.changesRevision], () => { if (!store.busy) void refreshTargetStatus() })
watch(pickerOpen, open => { if (open) void refreshTargetStatus() })

async function send() {
  const text = sender.value?.getModelValue().text.trim()
  if (!text || !writable.value || store.busy) return
  if (await store.send({ message: text, chapter_id: props.chapterId || null, model_config_id: Number(modelId.value) || null, targets: targets.value })) sender.value?.clear()
}

async function operation(action: () => Promise<unknown>) {
  operationBusy.value = true
  try { await action() } catch (error) { notice.error(error instanceof Error ? error.message : '操作失败') }
  finally { operationBusy.value = false }
}

function conversationLabel(conversation: { id: number; updated_at: string }) {
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

onBeforeUnmount(() => { catalogEpoch += 1; statusEpoch += 1; senderObserver?.disconnect(); window.removeEventListener('focus', refreshTargetStatus); store.disconnect() })
onMounted(async () => {
  window.addEventListener('focus', refreshTargetStatus)
  await nextTick()
  // XSender mounts its editor asynchronously and currently exposes no ARIA input props.
  function labelEditor() {
    const editor = panel.value?.querySelector('[contenteditable="true"]')
    if (!editor) return
    editor.setAttribute('role', 'textbox')
    editor.setAttribute('aria-label', '创作要求')
    editor.setAttribute('aria-multiline', 'true')
    senderObserver?.disconnect()
  }
  senderObserver = new MutationObserver(labelEditor)
  if (panel.value) senderObserver.observe(panel.value, { childList: true, subtree: true, attributes: true, attributeFilter: ['contenteditable'] })
  labelEditor()
})
</script>

<template>
  <aside ref="panel" class="creation-agent-panel" :class="{ 'is-workflow': workflow }" aria-label="创作助手" @keydown.esc.stop="close">
    <header>
      <div><Bot :size="18" /><strong>创作助手</strong></div>
      <AppButton size="sm" icon-only aria-label="关闭创作助手" @click="close"><X :size="18" /></AppButton>
    </header>
    <div class="creation-agent-panel__toolbar" aria-label="对话管理">
      <label class="creation-agent-panel__conversation-select">
        <History :size="15" aria-hidden="true" />
        <span>对话记录</span>
        <select aria-label="对话记录" :value="store.conversationId || ''" :disabled="store.busy || !store.conversations.length" @change="operation(() => store.selectConversation(Number(($event.target as HTMLSelectElement).value)))">
          <option v-if="!store.conversations.length" value="">暂无记录</option>
          <option v-for="conversation in store.conversations" :key="conversation.id" :value="conversation.id">{{ conversationLabel(conversation) }}</option>
        </select>
      </label>
      <AppButton size="sm" variant="soft" aria-label="新建对话" :disabled="store.busy || operationBusy" @click="operation(store.newConversation)"><Plus :size="15" />新会话</AppButton>
    </div>
    <div class="creation-agent-panel__scope">
      <AppButton size="xs" :aria-expanded="pickerOpen" @click="pickerOpen = !pickerOpen">{{ targets.length ? `修改范围：已选 ${targets.length} 个对象` : '选择需要修改的对象' }}</AppButton>
      <span>仅图片与分镜提示词</span>
    </div>
    <p v-if="pendingCount" class="creation-agent-panel__constraint-notice" role="status">当前可选对象中有 {{ pendingCount }} 个需核对新约束，历史提示词尚未自动更新。<AppButton size="xs" @click="pickerOpen = true">查看对象</AppButton></p>
    <p v-if="statusError" class="creation-agent-panel__constraint-notice" role="status">{{ statusError }}</p>
    <div v-if="pickerOpen" class="creation-agent-panel__picker" aria-label="修改对象">
      <p v-if="catalogLoading">正在加载…</p>
      <label v-for="option in options" :key="option.key">
        <input v-model="selected" type="checkbox" :value="option.key" :disabled="store.busy || (!selected.includes(option.key) && selected.length >= (store.capabilities?.max_targets || 1))" @change="scopeEdited = true" />
        <span>{{ option.label }} <AppBadge v-if="pendingConstraints[option.key]?.length" tone="warning" size="sm">待核对约束</AppBadge>
          <small v-for="rule in pendingConstraints[option.key]" :key="rule.id" class="creation-agent-panel__pending-rule">{{ rule.content }}</small>
        </span>
      </label>
      <p v-if="!catalogLoading && !options.length">当前章节还没有可修改的对象。</p>
      <AppButton v-if="hasMoreAssets || hasMoreScenes" size="xs" :loading="catalogLoading" @click="loadTargets(true)">加载更多对象</AppButton>
    </div>
    <p v-if="store.loading" class="creation-agent-panel__hint">正在恢复对话…</p>
    <p v-else-if="!store.capabilities?.enabled" class="creation-agent-panel__hint">创作助手尚未启用，请联系管理员。</p>
    <p v-else-if="!store.capabilities.can_write" class="creation-agent-panel__hint">当前账号可以查看自己的对话，修改需要创作者权限。</p>
    <div v-if="!store.messages.length && !store.loading" class="creation-agent-panel__welcome">
      <Bot :size="30" />
      <strong>说出你希望的画面</strong>
      <p>例如：“这几个镜头的光线更柔和，人物外貌保持一致。”</p>
      <span>你可以查看每次改动，也可以撤销。</span>
    </div>
    <AppButton v-if="store.nextBefore" size="xs" @click="operation(() => store.history(store.nextBefore || undefined))">查看更早的消息</AppButton>
    <BubbleList v-if="store.messages.length" class="creation-agent-panel__messages" :list="bubbles" :auto-scroll="true" :show-back-button="true" max-height="100%">
      <template #content="{ item }"><div class="creation-agent-panel__message">{{ item.content }}</div></template>
      <template #footer="{ item }">
        <PromptChangeCard v-for="change in item.changes" :key="change.id" :change="change" :can-undo="Boolean(writable && !store.busy && !operationBusy)"
          @undo="operation(() => store.undo($event))" @locate="operation(() => locate($event))" />
      </template>
      <template #backToBottom="{ unreadCount, scrollToBottom }"><AppButton size="xs" variant="secondary" @click="scrollToBottom()">{{ unreadCount ? `${unreadCount} 条新消息` : '回到最新' }}</AppButton></template>
    </BubbleList>
    <footer>
      <div v-if="store.statusText" class="creation-agent-panel__status" role="status">{{ store.statusText }}</div>
      <p v-if="store.error" class="creation-agent-panel__error" role="alert">{{ store.error }}</p>
      <AppButton v-if="store.currentRun && !store.streamConnected && store.busy" size="xs" @click="store.follow(store.currentRun.task_id)"><RefreshCw :size="13" />重新连接</AppButton>
      <XSender ref="sender" placeholder="描述你希望调整的画面…" :max-length="8000" :disabled="!writable || !modelId || store.submitting" :loading="store.busy" submit-type="enter" :auto-focus="true" :tip-config="false" @submit="send" @cancel="operation(store.stop)">
        <template #action-list>
          <AppButton v-if="store.busy" size="sm" icon-only aria-label="停止创作助手" @click="operation(store.stop)"><Square :size="15" /></AppButton>
          <AppButton v-else size="sm" variant="soft" icon-only aria-label="发送创作要求" :disabled="!writable || !modelId || sender?.senderState.isEmpty" @click="send"><ArrowUp :size="17" /></AppButton>
        </template>
        <template #footer>
          <div class="creation-agent-panel__composer-tools">
            <label class="creation-agent-panel__model-select">
              <Sparkles :size="13" aria-hidden="true" />
              <span>模型</span>
              <select v-model="modelId" aria-label="助手模型" :disabled="store.busy">
                <option v-if="!store.capabilities?.models.length" value="">尚无可用模型</option>
                <option v-for="model in store.capabilities?.models" :key="model.id" :value="String(model.id)">{{ model.name }}</option>
              </select>
            </label>
            <span class="creation-agent-panel__send-hint">Enter 发送</span>
          </div>
        </template>
      </XSender>
    </footer>
  </aside>
</template>

<style scoped>
.creation-agent-panel { --el-color-primary: var(--app-accent); --el-bg-color: var(--app-surface); --el-bg-color-overlay: var(--app-surface); --el-fill-color: var(--app-surface-muted); --el-fill-color-light: var(--app-surface-muted); --el-fill-color-blank: var(--app-surface); --el-text-color-primary: var(--app-text); --el-text-color-regular: var(--app-text-secondary); --el-border-color: var(--app-border); --el-border-color-light: var(--app-border); --el-border-radius-base: 10px; --el-font-size-base: 13px; --el-font-line-height-primary: 1.65; position: sticky; top: var(--short-drama-header-height, 72px); flex: 0 0 var(--short-drama-assistant-width, 420px); width: var(--short-drama-assistant-width, 420px); min-width: 0; height: calc(100dvh - var(--short-drama-header-height, 72px)); display: flex; flex-direction: column; border-left: 1px solid var(--app-border); color: var(--app-text); background: var(--app-surface); overflow: hidden; font-size: 13px; }
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
.creation-agent-panel__picker { max-height: 180px; overflow: auto; flex-shrink: 0; margin: 0 12px; padding: 8px; border: 1px solid var(--app-border); border-radius: 10px; }
.creation-agent-panel__picker label { display: flex; align-items: flex-start; gap: 8px; padding: 6px 0; overflow-wrap: anywhere; }
.creation-agent-panel__picker input { accent-color: var(--app-accent); }
.creation-agent-panel__hint { padding: 10px 16px; color: var(--app-text-secondary); }
.creation-agent-panel__welcome { flex: 1; display: flex; flex-direction: column; align-items: flex-start; justify-content: center; padding: 28px; gap: 12px; }
.creation-agent-panel__welcome > svg { color: var(--app-accent); }
.creation-agent-panel__welcome p { color: var(--app-text-secondary); line-height: 1.8; margin: 0; }
.creation-agent-panel__welcome span { font-size: 12px; color: var(--app-text-secondary); }
.creation-agent-panel__messages { flex: 1; min-height: 0; padding: 10px 14px; overflow: auto; }
.creation-agent-panel__message { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.7; }
.creation-agent-panel footer { padding: 12px; border-top: 1px solid var(--app-border); margin-top: auto; background: color-mix(in srgb,var(--app-surface) 96%,var(--app-accent)); }
.creation-agent-panel footer :deep(.elx-x-sender) { overflow: hidden; border: 1px solid var(--app-border); border-radius: 15px; background: var(--app-surface); box-shadow: 0 4px 16px rgb(35 39 55 / 7%); }
.creation-agent-panel footer :deep(.elx-x-sender:focus-within) { border-color: color-mix(in srgb,var(--app-accent) 52%,var(--app-border)); box-shadow: 0 0 0 3px color-mix(in srgb,var(--app-accent) 12%,transparent),0 5px 18px rgb(35 39 55 / 8%); }
.creation-agent-panel footer :deep(.elx-x-sender::after) { display: none; }
.creation-agent-panel footer :deep(.elx-x-sender__footer) { border-top-color: color-mix(in srgb,var(--app-border) 75%,transparent); }
.creation-agent-panel__composer-tools { display: flex; min-width: 0; min-height: 38px; align-items: center; justify-content: space-between; gap: 8px; padding: 5px 56px 5px 9px; }
.creation-agent-panel__model-select { display: inline-flex; min-width: 0; max-width: 190px; height: 28px; align-items: center; gap: 5px; padding: 0 7px; border-radius: 8px; color: var(--app-text-secondary); background: var(--app-surface-muted); font-size: 10px; }
.creation-agent-panel__model-select > span { color: var(--app-text-muted); }
.creation-agent-panel__model-select select { width: auto; max-width: 130px; height: 26px; border: 0; padding: 0 3px; color: var(--app-text-secondary); background: transparent; font-size: 11px; font-weight: 620; }
.creation-agent-panel__send-hint { flex: 0 0 auto; color: var(--app-text-muted); font-size: 10px; white-space: nowrap; }
.creation-agent-panel__status { color: var(--app-text-secondary); margin-bottom: 8px; font-size: 12px; }
.creation-agent-panel__error { color: var(--app-text); border-left: 3px solid var(--app-accent); padding-left: 8px; font-size: 12px; }
.creation-agent-panel :deep(.elx-bubble__avatar-placeholder) { display: none; }
.creation-agent-panel :deep(.elx-bubble__content--filled) { background: var(--app-accent-soft); }
.creation-agent-panel :deep([contenteditable]) { color: var(--app-text); max-height: 160px; overflow-y: auto; }
@media (max-width: 760px) { .creation-agent-panel { flex: 1 1 100%; width: 100%; border-left: 0; } }
</style>
