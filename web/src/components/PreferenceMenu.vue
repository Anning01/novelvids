<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch, type Component } from 'vue'
import { Check } from 'lucide-vue-next'
import { tr } from '@/i18n'
import { claimExclusivePopover } from '@/shared/exclusivePopover'

export interface PreferenceOption { value: string; label: string; icon?: Component }
const props = withDefaults(defineProps<{
  modelValue: string
  options: PreferenceOption[]
  label: string
  placement?: 'sidebar' | 'floating' | 'inline'
  loading?: boolean
  disabled?: boolean
  busy?: boolean
}>(), { placement: 'sidebar', loading: false, disabled: false, busy: false })
const emit = defineEmits<{ 'update:modelValue': [value: string]; open: []; close: [] }>()
const root = ref<HTMLElement>(), panel = ref<HTMLElement>()
const open = ref(false)
const source = Symbol('preference-menu')
let release: (() => void) | undefined

function close(restoreFocus = false) {
  if (!open.value) return
  open.value = false
  release?.(); release = undefined
  emit('close')
  if (restoreFocus) root.value?.querySelector<HTMLButtonElement>('button')?.focus()
}
function focusSelection() {
  const selected = panel.value?.querySelector<HTMLButtonElement>('[aria-checked="true"]:not(:disabled)')
    ?? panel.value?.querySelector<HTMLButtonElement>('[role="menuitemradio"]:not(:disabled)')
  ;(selected ?? panel.value)?.focus()
}
async function toggle() {
  if (props.busy) return
  if (open.value) { close(); return }
  release = claimExclusivePopover(source, () => close())
  open.value = true
  emit('open')
  await nextTick()
  focusSelection()
}
function select(value: string) {
  if (props.disabled || props.loading || props.busy) return
  close(true)
  if (value !== props.modelValue) emit('update:modelValue', value)
}
function keydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && open.value) {
    event.preventDefault(); event.stopPropagation(); close(true); return
  }
  const buttons = Array.from(panel.value?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]:not(:disabled)') ?? [])
  if (!buttons.length) return
  const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
  if (['Enter', ' '].includes(event.key) && index >= 0) {
    event.preventDefault(); select(buttons[index]!.dataset.preferenceValue!); return
  }
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
    : (index + (event.key === 'ArrowUp' ? -1 : 1) + buttons.length) % buttons.length
  buttons[next]?.focus()
}
function outside(event: Event) {
  if (event.target instanceof Node && !root.value?.contains(event.target)) close()
}
watch(() => props.loading, async loading => { if (open.value && !loading) { await nextTick(); focusSelection() } })
onMounted(() => {
  document.addEventListener('pointerdown', outside)
  document.addEventListener('focusin', outside)
})
onBeforeUnmount(() => {
  close()
  release?.()
  document.removeEventListener('pointerdown', outside)
  document.removeEventListener('focusin', outside)
})
</script>

<template>
  <div ref="root" class="preference-menu" @keydown="keydown">
    <slot name="trigger" :toggle="toggle" :open="open" />
    <section v-if="open" ref="panel" class="preference-menu__panel" :class="`is-${placement}`"
      role="menu" :aria-label="label" :aria-busy="loading || busy" tabindex="-1">
      <p v-if="loading" role="status">{{ tr('加载中…') }}</p>
      <template v-else>
        <button v-for="option in options" :key="option.value" type="button" role="menuitemradio"
          :data-preference-value="option.value" :aria-checked="modelValue === option.value"
          :tabindex="modelValue === option.value ? 0 : -1" :disabled="disabled || busy" @click="select(option.value)">
          <component v-if="option.icon" :is="option.icon" :size="15" aria-hidden="true" />
          <span>{{ option.label }}</span><Check v-if="modelValue === option.value" :size="14" aria-hidden="true" />
        </button>
      </template>
      <slot />
    </section>
  </div>
</template>

<style scoped>
.preference-menu { position: relative; }
.preference-menu__panel { position: absolute; z-index: 5; bottom: calc(100% + 8px); left: 0; display: grid; gap: 2px; width: 176px; max-width: calc(100vw - 92px); max-height: calc(100dvh - 120px); overflow-y: auto; box-sizing: border-box; padding: 6px; border: 1px solid var(--app-border); border-radius: 9px; outline: none; color: var(--app-text); background: var(--app-surface); box-shadow: var(--app-shadow); }
.preference-menu__panel.is-floating, .preference-menu__panel.is-inline { right: 0; left: auto; }
.preference-menu__panel.is-inline { top: calc(100% + 8px); bottom: auto; }
.preference-menu__panel > button { display: flex; width: 100%; min-height: 34px; align-items: center; gap: 8px; padding: 6px 9px; border: 0; border-radius: 6px; color: var(--app-text); background: transparent; text-align: left; font: inherit; font-size: 13px; cursor: pointer; }
.preference-menu__panel > button > span { flex: 1; }
.preference-menu__panel > button:hover:not(:disabled) { background: var(--app-surface-hover); }
.preference-menu__panel > button[aria-checked='true'] { color: var(--app-accent); background: var(--app-accent-soft); }
.preference-menu__panel > button:focus-visible { outline: 2px solid var(--app-accent); outline-offset: -2px; }
.preference-menu__panel > button:disabled { cursor: default; }
.preference-menu__panel > button:disabled:not([aria-checked='true']) { opacity: .55; }
.preference-menu__panel :deep(p) { margin: 6px; font-size: 11px; line-height: 1.5; color: var(--app-text-secondary); }
@media (max-width: 720px) { .preference-menu__panel.is-sidebar { position: fixed; left: 76px; bottom: 12px; } }
</style>
