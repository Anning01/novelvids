<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ElPopover } from 'element-plus'
import { Check, ChevronDown, History, MessageSquare, Plus, RotateCcw, Search, Trash2, X } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import type { AgentConversation } from './types'

const props = defineProps<{
  conversations: AgentConversation[]
  deletedConversations: AgentConversation[]
  currentId: number | null
  disabled: boolean
  workflow?: boolean
}>()
const emit = defineEmits<{ select: [id: number]; create: []; delete: [id: number]; restore: [id: number]; loadDeleted: [] }>()
const open = ref(false)
const deleted = ref(false)
const search = ref('')
const confirming = ref<number | null>(null)
const trigger = ref<InstanceType<typeof AppButton> | null>(null)
const searchInput = ref<HTMLInputElement | null>(null)
const current = computed(() => props.conversations.find(item => item.id === props.currentId))
const title = (item?: AgentConversation) => item?.title?.trim() || '新会话'
const rows = computed(() => (deleted.value ? props.deletedConversations : props.conversations)
  .filter(item => title(item).toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase())))
const time = (value: string) => {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '刚刚'
  const today = new Date().toDateString() === date.toDateString()
  return new Intl.DateTimeFormat('zh-CN', today
    ? { hour: '2-digit', minute: '2-digit', hour12: false }
    : { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }).format(date)
}
function close() {
  open.value = false
  confirming.value = null
  void nextTick(() => trigger.value?.$el?.focus())
}
function switchView() {
  deleted.value = !deleted.value
  confirming.value = null
  search.value = ''
  if (deleted.value) emit('loadDeleted')
}
function select(id: number) { emit('select', id); close() }
function create() { emit('create'); open.value = false }
watch(open, value => {
  confirming.value = null
  if (value) { search.value = ''; deleted.value = false }
})
watch(() => props.conversations.map(item => item.id).join(','), () => { confirming.value = null })
</script>

<template>
  <div class="agent-conversations" aria-label="对话管理">
    <ElPopover :visible="open" :disabled="disabled && !open" trigger="click" placement="bottom-start" :width="380" :show-arrow="false"
      :popper-class="['agent-conversation-popover', { 'is-workflow': workflow }]" :popper-style="{ padding: '0', maxWidth: 'calc(100vw - 24px)' }"
      @update:visible="open = $event" @after-enter="searchInput?.focus()">
      <template #reference>
        <AppButton ref="trigger" class="agent-conversations__trigger" size="sm" :disabled="disabled" aria-label="对话记录" title="查看对话记录" aria-haspopup="dialog" :aria-expanded="open">
          <History :size="14" class="agent-conversations__history" />
          <span class="agent-conversations__current" :title="title(current)">{{ title(current) }}</span>
          <ChevronDown :size="13" class="agent-conversations__chevron" />
        </AppButton>
      </template>
      <section class="agent-conversation-list" role="dialog" aria-label="会话列表" :aria-busy="disabled" @keydown.esc.stop.prevent="close">
        <header><div><strong>{{ deleted ? '已删除会话' : '最近会话' }}</strong><span>{{ deleted ? '恢复后可继续查看和对话' : '选择一个会话，接着创作' }}</span></div><AppButton size="sm" icon-only aria-label="关闭会话列表" @click="close"><X :size="16" /></AppButton></header>
        <label class="agent-conversation-list__search"><Search :size="15" /><input ref="searchInput" v-model="search" type="search" :placeholder="deleted ? '搜索已删除会话' : '搜索最近会话'" aria-label="搜索会话" /></label>
        <ul aria-label="会话记录">
          <li v-for="item in rows" :key="item.id" :class="{ 'is-current': !deleted && item.id === currentId }">
            <template v-if="confirming !== item.id">
              <button class="agent-conversation-list__item" type="button" :disabled="disabled || deleted" :aria-current="!deleted && item.id === currentId ? 'true' : undefined" :aria-label="`打开会话：${title(item)}`" @click="select(item.id)">
                <MessageSquare :size="16" /><span><strong :title="title(item)">{{ title(item) }}</strong><small><time :datetime="item.updated_at">{{ time(item.updated_at) }}</time><span v-if="!deleted && item.id === currentId"> · 当前会话</span></small></span><Check v-if="!deleted && item.id === currentId" :size="14" />
              </button>
              <AppButton v-if="deleted" size="sm" icon-only :disabled="disabled" :aria-label="`恢复会话：${title(item)}`" title="恢复会话" @click="emit('restore', item.id)"><RotateCcw :size="15" /></AppButton>
              <AppButton v-else class="agent-conversation-list__delete" size="sm" icon-only :disabled="disabled" :aria-label="`删除会话：${title(item)}`" title="删除会话" @click="confirming = item.id"><Trash2 :size="15" /></AppButton>
            </template>
            <div v-else class="agent-conversation-list__confirm" role="group" aria-label="确认删除会话">
              <strong>删除“{{ title(item) }}”？</strong><p>已保存的设定与分镜会保留，会话可恢复。</p>
              <div><AppButton size="xs" :disabled="disabled" @click="confirming = null">取消</AppButton><AppButton size="xs" variant="danger" :disabled="disabled" @click="emit('delete', item.id)">删除会话</AppButton></div>
            </div>
          </li>
        </ul>
        <div v-if="!rows.length" class="agent-conversation-list__empty"><MessageSquare :size="25" /><strong>{{ disabled ? '正在加载会话…' : search ? '没有找到相关会话' : deleted ? '没有已删除的会话' : '还没有对话记录' }}</strong><span v-if="!disabled">{{ search ? '换个关键词试试' : deleted ? '删除的会话会保留在这里' : '新建一个会话，开始这次创作' }}</span></div>
        <footer><AppButton size="xs" :disabled="disabled" @click="switchView"><component :is="deleted ? History : Trash2" :size="13" />{{ deleted ? '返回最近会话' : '已删除' }}</AppButton><span>最近 30 条</span></footer>
      </section>
    </ElPopover>
    <AppButton class="agent-conversations__new" size="sm" :disabled="disabled" aria-label="新建对话" @click="create"><Plus :size="14" />新会话</AppButton>
  </div>
</template>

<style>
.agent-conversation-popover.el-popper { overflow: hidden; color: var(--app-text); background: var(--app-surface); border: 1px solid var(--app-border); border-radius: 14px; box-shadow: 0 12px 36px rgb(0 0 0 / 20%); }
</style>
<style scoped>
.agent-conversations { display: flex; align-items: center; gap: 4px; min-width: 0; padding: 3px 8px 0; flex-shrink: 0; }
.agent-conversations__trigger { flex: 0 1 auto; min-width: 0; height: 28px; min-height: 28px; padding: 0 5px; gap: 5px; text-align: left; border-radius: 7px; }
.agent-conversations__trigger:hover:not(:disabled),.agent-conversations__trigger[aria-expanded=true] { color: var(--app-text); background: var(--app-surface-hover); }
.agent-conversations__history,.agent-conversations__chevron { flex-shrink: 0; color: var(--app-text-muted); }
.agent-conversations__current { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; font-weight: 500; line-height: 1.4; }
.agent-conversations__new { flex: 0 0 auto; margin-left: auto; height: 28px; min-height: 28px; padding-inline: 5px; gap: 4px; border-radius: 7px; font-weight: 500; color: var(--app-accent); }
.agent-conversations__new:hover:not(:disabled) { color: var(--app-accent); background: var(--app-accent-soft); }
.agent-conversation-list { color: var(--app-text); font-size: 12px; }
header { display: flex; justify-content: space-between; align-items: center; padding: 12px 12px 8px 16px; }header > div { display: grid; gap: 4px; }header strong { font-size: 14px; }header span { font-size: 11px; color: var(--app-text-muted); }
.agent-conversation-list__search { display: flex; align-items: center; gap: 8px; margin: 4px 12px 8px; padding: 9px 10px; border: 1px solid var(--app-border); border-radius: 8px; color: var(--app-text-muted); background: var(--app-surface-muted); }
.agent-conversation-list__search:focus-within { border-color: var(--app-accent); }.agent-conversation-list__search input { width: 100%; min-width: 0; border: 0; outline: 0; color: var(--app-text); background: transparent; font: inherit; }
ul { list-style: none; margin: 0; padding: 0 6px; overflow-y: auto; max-height: min(360px, 45dvh); overscroll-behavior: contain; }li { display: flex; align-items: center; gap: 4px; padding: 2px 6px 2px 2px; margin-block: 2px; border-radius: 9px; }li:hover { background: var(--app-surface-hover); }li.is-current { background: var(--app-accent-soft); }
.agent-conversation-list__item { display: flex; align-items: center; gap: 10px; min-width: 0; flex: 1; min-height: 62px; padding: 10px; text-align: left; color: var(--app-text); border: 0; background: transparent; font: inherit; cursor: pointer; }.agent-conversation-list__item > svg { flex-shrink: 0; color: var(--app-text-muted); }.is-current .agent-conversation-list__item > svg { color: var(--app-accent); }
.agent-conversation-list__item > span { display: grid; gap: 5px; min-width: 0; flex: 1; }.agent-conversation-list__item strong { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere; font-weight: 500; line-height: 1.5; }.agent-conversation-list__item small { color: var(--app-text-muted); font-size: 10px; }.agent-conversation-list__item:focus-visible { outline: 2px solid var(--app-accent); outline-offset: -2px; border-radius: 7px; }.agent-conversation-list__item:disabled { cursor: default; }
.agent-conversation-list__delete { color: var(--app-text-muted); }.agent-conversation-list__delete:hover:not(:disabled) { color: var(--app-danger, #d36371); background: var(--app-surface-muted); }
.agent-conversation-list__confirm { width: 100%; padding: 10px; }.agent-conversation-list__confirm > strong { display: block; overflow-wrap: anywhere; line-height: 1.5; }.agent-conversation-list__confirm p { margin: 6px 0 10px; color: var(--app-text-muted); font-size: 11px; }.agent-conversation-list__confirm > div { display: flex; justify-content: flex-end; gap: 6px; }
.agent-conversation-list__empty { display: grid; justify-items: center; gap: 8px; padding: 26px 12px; color: var(--app-text-muted); }.agent-conversation-list__empty strong { color: var(--app-text-secondary); font-weight: 500; }.agent-conversation-list__empty span { font-size: 11px; }
footer { display: flex; align-items: center; justify-content: space-between; margin-top: 6px; padding: 8px 12px; border-top: 1px solid var(--app-border); color: var(--app-text-muted); }footer > span { font-size: 10px; }
</style>
