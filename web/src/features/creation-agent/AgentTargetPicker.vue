<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { ElPopover } from 'element-plus'
import { Check, Clapperboard, Image, MapPin, Package, Plus, Search, UsersRound, X } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import { AssetTypeEnum } from '@/types'
import { targetKey, type AgentTargetOption } from './workspace'
import type { PromptTargetStatus } from './types'

const props = defineProps<{
  open: boolean
  modelValue: string[]
  options: AgentTargetOption[]
  limit: number
  loading: boolean
  hasMore: boolean
  disabled: boolean
  pending: Record<string, PromptTargetStatus['pending_constraints']>
}>()
const emit = defineEmits<{
  'update:open': [value: boolean]
  'update:modelValue': [value: string[]]
  refresh: []
  more: []
  done: []
}>()
const search = ref('')
const filter = ref('all')
const searchInput = ref<HTMLInputElement | null>(null)
const trigger = ref<InstanceType<typeof AppButton> | null>(null)
const filters = [{ key: 'all', label: '全部' }, { key: 'character', label: '角色' }, { key: 'setting', label: '场景' }, { key: 'prop', label: '道具' }, { key: 'scene', label: '分镜' }, { key: 'selected', label: '已选' }]
function category(option: AgentTargetOption) {
  if (option.target.kind === 'scene') return 'scene'
  if (option.assetType === AssetTypeEnum.PERSON) return 'character'
  if (option.assetType === AssetTypeEnum.SCENE) return 'setting'
  if (option.assetType === AssetTypeEnum.ITEM) return 'prop'
  return 'image'
}
function icon(option: AgentTargetOption) { return { scene: Clapperboard, character: UsersRound, setting: MapPin, prop: Package, image: Image }[category(option)] }
const displayLabel = (option: AgentTargetOption) => option.label.replace(/@\{([^{}]+)\}/g, '$1')
const visibleOptions = computed(() => props.options.filter(option =>
  (filter.value === 'all' || (filter.value === 'selected' ? props.modelValue.includes(targetKey(option.target)) : category(option) === filter.value))
  && displayLabel(option).toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase())))
function toggle(key: string) {
  if (props.disabled) return
  if (props.modelValue.includes(key)) emit('update:modelValue', props.modelValue.filter(value => value !== key))
  else if (props.modelValue.length < props.limit) emit('update:modelValue', [...props.modelValue, key])
}
function close() { emit('update:open', false); void nextTick(() => trigger.value?.$el?.focus()) }
function done() { emit('update:open', false); emit('done') }
function opened() { search.value = ''; void nextTick(() => searchInput.value?.focus()) }
</script>

<template>
  <ElPopover :visible="open" trigger="click" placement="top-start" :width="380" :show-arrow="false" popper-class="agent-target-popover" :popper-style="{ padding: '0', maxWidth: 'calc(100vw - 24px)' }" @update:visible="emit('update:open', $event)" @after-enter="opened">
    <template #reference><AppButton ref="trigger" size="sm" class="agent-target-trigger" :disabled="disabled" :aria-expanded="open" aria-label="选择修改对象" aria-haspopup="dialog"><Plus :size="15" />{{ modelValue.length ? `修改对象 · ${modelValue.length}` : '指定对象' }}</AppButton></template>
    <section class="agent-target-picker" role="dialog" aria-label="选择修改对象" @keydown.esc.stop.prevent="close">
      <header><div><strong>选择修改对象</strong><span>可多选，最多 {{ limit }} 个</span></div><AppButton icon-only size="sm" aria-label="关闭对象选择" @click="close"><X :size="16" /></AppButton></header>
      <label class="agent-target-picker__search"><Search :size="16" /><input ref="searchInput" v-model="search" type="search" aria-label="搜索修改对象" placeholder="搜索名称或分镜内容" /></label>
      <nav aria-label="对象类型"><button v-for="tab in filters" :key="tab.key" type="button" :aria-pressed="filter === tab.key" @click="filter = tab.key">{{ tab.label }}<span v-if="tab.key === 'selected'"> {{ modelValue.length }}</span></button></nav>
      <div class="agent-target-picker__list">
        <label v-for="option in visibleOptions" :key="targetKey(option.target)" class="agent-target-row" :class="{ 'is-selected': modelValue.includes(targetKey(option.target)), 'is-variant': option.target.kind === 'variant' }">
          <input type="checkbox" :value="targetKey(option.target)" :checked="modelValue.includes(targetKey(option.target))" :disabled="disabled || (!modelValue.includes(targetKey(option.target)) && modelValue.length >= limit)" @change="toggle(targetKey(option.target))" />
          <span class="agent-target-row__icon"><component :is="icon(option)" :size="17" /></span>
          <span class="agent-target-row__copy"><span :title="displayLabel(option)">{{ displayLabel(option) }}</span><small v-if="option.target.kind === 'variant'">衍生形象</small><details v-if="pending[targetKey(option.target)]?.length" @click.stop><summary>待核对约束</summary><p v-for="rule in pending[targetKey(option.target)]" :key="rule.id">{{ rule.content }}</p></details></span>
          <Check v-if="modelValue.includes(targetKey(option.target))" :size="17" class="agent-target-row__check" />
        </label>
        <p v-if="loading" class="agent-target-picker__empty">正在加载对象…</p>
        <p v-else-if="!visibleOptions.length" class="agent-target-picker__empty">{{ filter === 'selected' ? '还没有选中对象' : search ? '没有找到匹配对象' : '当前分类还没有对象' }}</p>
        <AppButton v-if="hasMore" size="sm" :loading="loading" @click="emit('more')">加载更多对象</AppButton>
      </div>
      <footer><div><span role="status">{{ modelValue.length >= limit ? '已达到选择上限' : `已选 ${modelValue.length} 个对象` }}</span><AppButton v-if="modelValue.length" size="xs" :disabled="disabled" @click="emit('update:modelValue', [])">清空</AppButton><AppButton v-else size="xs" :loading="loading" @click="emit('refresh')">刷新</AppButton></div><AppButton variant="primary" size="sm" @click="done">完成</AppButton></footer>
    </section>
  </ElPopover>
</template>

<style>
.agent-target-popover.el-popper { overflow: hidden; border: 1px solid var(--app-border); border-radius: 16px; color: var(--app-text); background: var(--app-surface); box-shadow: 0 12px 40px rgb(0 0 0 / 18%); }
</style>
<style scoped>
.agent-target-picker { display: flex; flex-direction: column; max-height: min(460px, calc(100dvh - 210px)); font-size: 13px; }
.agent-target-picker header { display: flex; align-items: center; justify-content: space-between; padding: 12px 14px 8px; }
.agent-target-picker header > div { display: grid; gap: 4px; }
.agent-target-picker header strong { font-size: 14px; }.agent-target-picker header span { font-size: 11px; color: var(--app-text-muted); }
.agent-target-picker__search { display: flex; align-items: center; gap: 8px; margin: 4px 14px 8px; padding: 9px 10px; border: 1px solid var(--app-border); border-radius: 9px; color: var(--app-text-muted); background: var(--app-surface-muted); }
.agent-target-picker__search:focus-within { border-color: var(--app-accent); }
.agent-target-picker__search input { min-width: 0; width: 100%; border: 0; outline: 0; color: var(--app-text); background: transparent; font: inherit; }
nav { display: flex; gap: 2px; padding: 0 12px 8px; border-bottom: 1px solid var(--app-border); }nav button { flex: 1; min-width: 0; padding: 9px 2px; border-radius: 7px; color: var(--app-text-secondary); background: transparent; font: inherit; font-size: 12px; cursor: pointer; }nav button[aria-pressed=true] { color: var(--app-accent); background: var(--app-accent-soft); }
.agent-target-picker__list { min-height: 80px; overflow-y: auto; padding: 6px; overscroll-behavior: contain; }
.agent-target-row { position: relative; display: flex; align-items: center; gap: 10px; min-height: 48px; margin: 2px 0; padding: 8px 10px; border-radius: 9px; cursor: pointer; }
.agent-target-row:hover { background: var(--app-surface-hover); }.agent-target-row.is-selected { background: var(--app-accent-soft); }.agent-target-row:has(input:focus-visible) { outline: 2px solid var(--app-accent); outline-offset: -2px; }.agent-target-row:has(input:disabled) { opacity: .5; cursor: not-allowed; }
.agent-target-row > input { position: absolute; width: 1px; height: 1px; opacity: 0; }.agent-target-row__icon { display: grid; flex-shrink: 0; place-items: center; width: 32px; height: 32px; border-radius: 8px; color: var(--app-text-secondary); background: var(--app-surface-muted); }.agent-target-row.is-variant .agent-target-row__icon { margin-left: 12px; }
.agent-target-row__copy { display: grid; gap: 3px; min-width: 0; flex: 1; }.agent-target-row__copy > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.agent-target-row__copy small { font-size: 11px; color: var(--app-text-muted); }.agent-target-row__copy details { color: var(--app-text-secondary); font-size: 11px; }.agent-target-row__copy p { margin: 5px 0; line-height: 1.6; }.agent-target-row__check { flex-shrink: 0; color: var(--app-accent); }
.agent-target-picker__empty { padding: 20px 10px; text-align: center; color: var(--app-text-muted); }
footer { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 10px 14px; border-top: 1px solid var(--app-border); }footer > div { display: flex; align-items: center; gap: 5px; }footer span { font-size: 12px; color: var(--app-text-secondary); }
.agent-target-trigger { color: var(--app-text-secondary); font-weight: 500; }
</style>
